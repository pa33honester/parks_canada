import os
import time
import json
import requests
import uuid
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv, set_key
import threading

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

import firebase_admin
from firebase_admin import credentials, messaging
from store import Store

DEBUG = True

def _debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

class Scraper:
    def __init__(self):
        # initialize
        self.store = Store()

        # Initialize task scheduler
        self.lock = threading.Lock()
        self.is_running = False
        self.process = None

        # Initialize Firebase Cloud Messaging
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)

    def _date_str_(self, days_from_today: int) -> str:
        """
        Get the date string in 'YYYY-MM-DD' format for a given number of days from today.
        """
        target_date = self.today + timedelta(days=days_from_today)
        return target_date.strftime("%Y-%m-%d")

    def _init_session_(self):
        # Initialize Selenium Web Driver
        # options = Options()
        # options.add_argument("--headless")
        # self.driver = webdriver.Chrome(
        #     service=Service(ChromeDriverManager().install()), options=options
        # )
        # self.driver.get(self.store.get('url'))
        # self.driver.maximize_window()
        # time.sleep(5)
        # self.cart_uid = self.driver.execute_script(
        #     "return localStorage.getItem('cartUid');"
        # )
        # self.cart_transaction_uid = self.driver.execute_script(
        #     "return localStorage.getItem('cartTransactionUid');"
        # )
        # init request
        self.session = requests.Session()
        self.headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Origin": self.store.get('url'),
            "Referer": self.store.get('url'),
            "X-XSRF-TOKEN": self.session.cookies.get("XSRF-TOKEN", ""),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Sec-CH-UA": '"Microsoft Edge";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "app-language": "en-CA",
            "app-version": "5.98.197",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Expires": "0",
            "Request-Id": f"|{uuid.uuid4()}.{uuid.uuid4().hex[:12]}",
            "Traceparent": f"00-{uuid.uuid4().hex[:32]}-{uuid.uuid4().hex[:16]}-01",
        }

        self.api_calls = 0
        self.today = date.today()
        self.parks = self.store.get('location')

    def _del_session_(self):
        # self.driver.quit()
        self.session.close()

    def _make_param_(self, mapId, startDate, endDate):

        utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        
        return {
            "mapId": mapId,
            "bookingCategoryId": 0,
            "equipmentCategoryId": -32768,
            "subEquipmentCategoryId": self.store.get('equipment'),
            # "cartUid": self.cart_uid,  # Update with current session value
            # "cartTransactionUid": self.cart_transaction_uid,  # Update with current session value
            # "bookingUid": "12f47a1c-f930-49f6-b5e5-8958dda7a9ee",  # Update with current session value
            "groupHoldUid": "",
            "startDate": startDate,
            "endDate": endDate,
            "getDailyAvailability": "false",
            "isReserving": "true",
            "filterData": json.dumps(
                [
                    {
                        "attributeDefinitionId": -32756,
                        "enumValues": [1],
                        "attributeDefinitionDecimalValue": 0,
                        "filterStrategy": 0,
                        "attributeType": 0,
                    }
                ]
            ),
            "boatLength": 0,
            "boatDraft": 0,
            "boatWidth": 0,
            "peopleCapacityCategoryCounts": json.dumps(
                [
                    {
                        "capacityCategoryId": -32767,
                        "subCapacityCategoryId": None,
                        "count": 1,
                        "isAdult": None,
                    }
                ]
            ),
            "numEquipment": 0,
            "seed": utc_time
        }

    def _request_(self, methods: str, url: str, headers=None, params=None, data=None):
        """
        Make a simple GET request to the specified URL.
        """

        time.sleep(1)

        if headers is None:
            headers = self.headers
        try:
            if methods == "GET":
                response = self.session.get(url, headers=headers, params=params)
            elif methods == "POST":
                response = self.session.post(url, headers=headers, params=params, data=data)
            else:
                _debug_print(f"Unsupported method: {methods}")
                return None
        except Exception as e:
            _debug_print(f"Request error: {e}")
            return None
            
        self.api_calls += 1
        _debug_print(f"API Call #{self.api_calls} responses with status code {response.status_code}")

        if response.status_code == 200:
            return response.json()
        else:
            return None

    def api_check(self, start: int, end: int, mapId=None):
        """ Check availability for a given date range and map ID.
        Args:
            start (int): Start date offset in days from today.
            end (int): End date offset in days from today.
            mapId (str, optional): Map ID to check availability for. Defaults to None.\
        Returns:
            bool: True if availability is found, False otherwise.
        """
        if mapId is None:
            mapId = self.store.get("westernMapId")

        startDate = self._date_str_(start)
        endDate = self._date_str_(end)

        response = self._request_(
            methods="GET",
            url=f"{self.store.get('url')}/api/availability/map",
            params=self._make_param_(mapId, startDate, endDate)
        )

        return response

    def fast_check(self, start: int, end: int) -> bool:
        """
            Fast Check If Given Date Range is Available
        """

        response = self.api_check(start, end)

        if response is None :
            return False
        
        try:
            mapLinkAvailabilities = response.get('mapLinkAvailabilities')

            for map_id in self.parks:
                if mapLinkAvailabilities.get(map_id)[0] == 0:
                    return True
            return False
        
        except Exception as e:
            _debug_print(f"Error in Fast-Check {e}")
            return False
        
    def find_date_range(self, min_block=5):
        
        total_days = self.store.get('days')
        found = 0, 0
        day = 0

        def expand_window(start):
            low = min_block
            high = total_days - start
            best_end = start + min_block - 1
            # Binary search for maximum available window
            while low <= high:
                mid = (low + high) // 2
                if self.fast_check(start, start + mid - 1):
                    best_end = start + mid - 1
                    low = mid + 1
                else:
                    high = mid - 1
            return best_end

        while day <= total_days - min_block:
            # First check if a large block is available
            if self.fast_check(day, day + min_block - 1):
                end = expand_window(day)
                if end - day > found[1] - found[0]:
                    found = (day, end)
                day = end + 1  # Jump past this block
            else:
                day += 1  # Slide forward

        # debug print the found ranges
        return found

    def find_sites(self, start, end, mapId, resourceLocationId = None):
        if resourceLocationId is None:
            resourceLocationId = self.store.find_location_id(mapId)

        response = self.api_check(start, end, mapId)

        if (
            response is None
            or response.get("mapAvailabilities") is None
            or response.get("mapAvailabilities")[0] != 0
        ):
            _debug_print( "Request failed...")
            return []

        mapLinkAvailabilities = response.get("mapLinkAvailabilities")
        resourceAvailabilities = response.get("resourceAvailabilities", {})

        result = []
        if mapLinkAvailabilities:
            for childMapId, availible in mapLinkAvailabilities.items():
                if availible[0] == 0:
                    result = result + self.find_sites(start, end, childMapId, resourceLocationId)
        elif resourceLocationId:
            for resourceId, available in resourceAvailabilities.items():
                if available[0].get("availability") == 0:
                    result.append( (mapId, resourceLocationId, resourceId) )
    
        return result
    
    def send_push(self, title, body):
        fcm_token = self.store.get('token')
        if not fcm_token:
            print("No FCM token provided!")
            return
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                token=fcm_token,
                data={
                    "title": str(title),
                    "body": str(body),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "unread": "true",
                },
            )
            print(f"FCM_TOKEN={fcm_token}")
            response = messaging.send(message)
            print("✅ Push sent:", response)
        except Exception as e:
            print(e)

    def make_booking_url(self, mapId, start, end, resourceLocationId = None):
        now = datetime.now()
        c_time = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(now.microsecond / 1000):03d}"
        startDate = self._date_str_(start)
        endDate = self._date_str_(end)
        url = f'{self.store.get('url')}/create-booking/results?mapId={mapId}&searchTabGroupId=0&bookingCategoryId=0&startDate={startDate}&endDate={endDate}&nights={end - start}&isReserving=true&equipmentId=-32768&subEquipmentId={self.store.get('equipment')}&peopleCapacityCategoryCounts=%5B%5B-32767,null,1,null%5D%5D&searchTime={c_time}&flexibleSearch=%5Bfalse,false,null,1%5D&filterData=%7B"-32756":"%5B%5B1%5D,0,0,0%5D"%7D'
        if resourceLocationId:
            url += f"&resourceLocationId={resourceLocationId}"
        return url

    def run(self):
        """
        Run the scraper to find available date ranges.
        This method will create threads for each range found and wait for them to complete.
        """

        # time log
        _start_time = time.time()

        # create session
        self._init_session_()

        # find available date range
        start, end = self.find_date_range()

        startDate = self._date_str_(start)
        endDate = self._date_str_(end)

        _debug_print(
            f"Handling range: {startDate} to {endDate}",
            "\n------------------------------\n",
        )


        fetched = self.api_check(start, end)
        response = fetched.get('mapLinkAvailabilities')
        
        search_results = {
            "search_time" : f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z",
            "start_date": startDate,
            "end_date": endDate,
            "data" : []
        }

        for map_id in self.parks:
            if response.get(map_id)[0] > 0: continue
            
            found_sites = self.find_sites(start, end, map_id)

            for map_id, location_id, resource_id in found_sites:

                location = self.store.find_location(location_id)
                resource = self.store.find_resource(resource_id)

                if location is None or resource is None:
                    continue

                search_results["data"].append({
                    "id": resource_id,
                    "resource": location["full_name"],
                    "description": location["description"],
                    "driving_direction": location["driving_directions"],
                    "website": location["website"],
                    "site": resource["name"],
                    "booking_url" : self.make_booking_url(map_id, start, end, location_id),
                    "capacity": resource["capacity"],
                    "start_date" : startDate,
                    "end_date" : endDate,
                    "added_to_cart" : False
                })

        _debug_print(
            f"Time: {time.time() - _start_time:.2f} seconds, API Calls : {self.api_calls}"
        )
        self.store.flush("searchResult", search_results)

        self.send_push(
            f"PARK Notification ({search_results['search_time']})",
            f"""
                Available Dates : {startDate} - {endDate}
                Available Parks : {len(search_results['data'])}
            """,
        )

        self._del_session_()

    def start(self):
        with self.lock:
            if self.process is not None:
                self.process.cancel()
            self.is_running = True
            self.run()
            self.process = threading.Timer(self.store.get('interval') * 60, self.start)
            self.process.start()

    def stop(self):
        with self.lock:
            self.is_running = False
            if self.process is not None:
                self.process.cancel()
                self.process = None

    def set_fcm_token(self, token):
        print(f"Token received :{token}")
        if token and token != self.store.get('token'):
            self.store.update({
                "token" : token
            })

    def update_setting(self, location: str, equipement: str, days: int, interval: int):
        self.store.update({
            "location" : location,
            "equipment" : equipement,
            "interval" : int(interval),
            "days" :   int(days)
        })

    def put_cart(self, new_cart):
        try:
            all_carts = self.store.load("cart")
            results = self.store.load("searchResult")

            new_carts = [cart for cart in all_carts if cart["id"] != new_cart["id"]]
            new_carts.append(new_cart)

            for i in range(len(results['data'])):
                if results['data'][i]['id'] == new_cart['id']:
                    results['data'][i]['added_to_cart'] = True
                    break

            self.store.flush("searchResult", results)
            self.store.flush("cart", new_carts)
        except Exception as e:
            _debug_print(f"Put Cart Error - {e}")

    def delete_cart(self, cart_id):
        try:
            all_carts = self.store.load('cart')
            search_results = self.store.load('searchResult')
            
            if cart_id == 'all':
                new_carts = []
            else :
                new_carts = [cart for cart in all_carts if cart["id"] != cart_id]

            for i in range(len(search_results['data'])):
                if search_results['data'][i]['id'] == cart_id:
                    search_results['data'][i].update({'added_to_cart' : False})
            
            self.store.flush('searchResult', search_results)
            self.store.flush('cart', new_carts)
        except Exception as e:
            _debug_print(f"Delete Cart Error - {e}")

if __name__ == "__main__":
    scraper = Scraper()
    scraper.run()
    input('Press Enter to Exit...')
