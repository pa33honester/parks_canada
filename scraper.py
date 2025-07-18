import os
import time
import json
import requests
import uuid
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv, set_key
import threading

from selenium import webdriver
# from seleniumwire import webdriver  # Note the change
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

import firebase_admin
from firebase_admin import credentials, messaging
from store import Store

DEBUG = True

def _debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

# Function to get localized display name
def get_localized_display_name(localized_values, culture_name):
    for value in localized_values:
        if value['cultureName'] == culture_name:
            return value['displayName']
    return None

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

    def date2str(self, days_from_today: int) -> str:
        """
        Get the date string in 'YYYY-MM-DD' format for a given number of days from today.
        """
        target_date = self.today + timedelta(days=days_from_today)
        return target_date.strftime("%Y-%m-%d")

    def _init_session_(self):
        # Initialize Selenium Web Driver
        # options = Options()
        # # options.add_argument("--headless")
        # self.driver = webdriver.Chrome(
        #     service=Service(ChromeDriverManager().install()), options=options
        # )
        # self.driver.maximize_window()
        # self.driver.get(self.store.get('url'))
        # time.sleep(5)
        # self.cart_uid = self.driver.execute_script(
        #     "return localStorage.getItem('cartUid');"
        # )

        self.api_calls = 0
        self.today = date.today()
        self.attribute_data = self.store.load('attributes')
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

        startDate = self.date2str(start)
        endDate = self.date2str(end)

        response = self._request_(
            methods="GET",
            url=f"{self.store.get('url')}/api/availability/map",
            params=self._make_param_(mapId, startDate, endDate)
        )

        return response

    def dfs(self, park_id, map_id = None, resourceLocationId = None) -> bool:

        if map_id == "-2147483403" or map_id == -2147483403: # ignore Jasper Overflow
            return False

        if map_id is None:
            map_id = park_id

        if resourceLocationId is None:
            resourceLocationId = self.store.find_location_id(map_id)

        response = self.api_check(0, 1, map_id)

        if response is None :
            print(f"Request Error {map_id}")
            return False
        
        try:
            mapLinkAvailabilities = response.get('mapLinkAvailabilities')
            resourceAvailabilities = response.get('resourceAvailabilities')

            if resourceAvailabilities:
                resources = self._request_("GET", f"https://reservation.pc.gc.ca/api/resourcelocation/resources?resourceLocationId={resourceLocationId}")
                print(f"resourceLocationId = {resourceLocationId}")

                for id in resourceAvailabilities.keys():
                    if resources.get(id) is None:
                        print(f"Not Found resource {id}")
                        continue
                    
                    row = self.store.fetch_one('resource_map', 'id = ?', (id,))
                    if row : 
                        print(f"Resource Already exist {id} - {row['park_id']} <> {park_id}")
                        continue

                    value = resources.get(id)
                    category = self.store.fetch_one('category', 'id = ?', (value['resourceCategoryId'],))['name']
                    self.store.insert('resource_map', {
                        "id"   : int(id),
                        'park_id' : park_id,
                        'map_id' : map_id,
                        'location_id' : resourceLocationId,
                        "name" : value['localizedValues'][0]['name'],
                        'description' : value['localizedValues'][0]['description'],
                        'category' : category,
                        'capacity' : value['maxCapacity'],
                        'photos' : json.dumps(value['photos']),
                        'max_stay' : value['maxStay']
                    })
            else :
                for child_map_id in mapLinkAvailabilities.keys():
                        self.dfs(park_id, child_map_id, resourceLocationId)

        except Exception as e:
            _debug_print(f"Fast-Check-Error {e}")

    def update_attributes(self):
        self._init_session_()

        # resource_location_list = self.store.fetch_all('location')
        resource_location_list = [{"id" : -2147483590}, {"id" : -2147483531}]

        total_changed = 0
        for resource_location in resource_location_list:
            resourceLocationId = resource_location['id']

            print(f"Resource Location #{resourceLocationId} is processing...")

            resource_list = self._request_("GET", f"https://reservation.pc.gc.ca/api/resourcelocation/resources?resourceLocationId={resourceLocationId}")

            if not resource_list:
                print(f"Resource Location #{resourceLocationId} could not resolve...")
                continue

            # Example: Mapping attributes
            for resource_id, resource_data in resource_list.items():

                # List to store attribute names and values
                attributes_list = []

                # Culture to display names (change as needed)
                culture_name = "en-CA"

                # Iterate over defined attributes to extract names and values
                for attr in resource_data['definedAttributes']:
                    attribute_definition_id = attr['attributeDefinitionId']
                    
                    
                    # Find corresponding attribute in attribute_json
                    if str(attribute_definition_id) not in self.attribute_data:
                        continue

                    attribute_details = self.attribute_data[str(attribute_definition_id)]
                    
                    # Get the display name for the attribute
                    attribute_name = get_localized_display_name(attribute_details['localizedValues'], culture_name)
                    
                    if attribute_details.get('values'):
                        # Get the values for the attribute
                        values = []
                        attribute_defined_values = attr.get('values', [])
                        for i in attribute_defined_values:
                            value = None
                            for t in attribute_details['values']:
                                if str(t['enumValue']) == str(i):
                                    value = t
                                    break
                            if value is None:
                                continue

                            value_name = get_localized_display_name(value['localizedValues'], culture_name)
                            values.append(value_name)
                        
                        # Append to the attributes list
                        attributes_list.append({
                            "attribute": attribute_name,
                            "value": ', '.join(values)
                        })
                    else :
                        attributes_list.append({
                            "attribute": attribute_name,
                            "value": f"[Min : {attribute_details['minValue']} - Max : {attribute_details['maxValue']}]"
                        })
                
                updated = self.store.update_row('resource_map', {"attr" : json.dumps(attributes_list).encode('utf-8')}, 'id = ?', (resource_id,))
                if updated :
                    total_changed += 1
        print(f"Total Changed : {total_changed}")

        self._del_session_()

    def find_availability(self, start , end , resourceId):
        """Finds available slots for a resource within a date range.
        Args:
            start: Start date of the search range.
            end: End date of the search range.
            resourceId: ID of the resource to check.
            
        Returns:
            A tuple of (start_index, end_index) if a suitable slot is found, else None.
        """
        # Constants (should be defined at class level)
        MIN_BLOCKS = self.store.get('blocks')
        DEFAULT_MAX_RANGE = 123456
        url = f"{self.store.get('url')}/api/availability/resourcedailyavailability"
        params = {
            # "cartUid": self.cart_uid,
            "resourceId" : resourceId,
            "bookingCategoryId" : 0,
            "startDate" : self.date2str(start),
            "endDate"   : self.date2str(end),
            "isReserving" :  True,
            "equipmentCategoryId" : -32768, 
            "subEquipmentCategoryId" :  -32759,
            "boatLength" : 0,
            "boatDraft" : 0,
            "boatWidth" : 0,
            "peopleCapacityCategoryCounts" : json.dumps([{
                "capacityCategoryId":-32767,
                "subCapacityCategoryId":None,
                "count":1
            }]),
            "numEquipment" : 0,
            "filterData" : json.dumps([{
                "attributeDefinitionId":-32756,
                "attributeDefinitionDecimalValue":0,
                "enumValues" : [1],
                "filterStrategy" : 0,
                "attributeType" : 0
            }]),
            "groupHoldUid" : None
        }

        try:
            response = self._request_("GET", url, params=params)
            # Debugging output
            with open("test.json", "w") as f:
                json.dump(response, f, indent=4)
        except Exception as e:  # Replace with specific exception
            _debug_print(f"Failed to check availability for resource #{resourceId}: {str(e)}")
            return None

        if not response:
            return None

        found_start, found_end = DEFAULT_MAX_RANGE, -1
        min_required_range = min(MIN_BLOCKS, 6)  # Use consistent minimum range

        for i, day_data in enumerate(response):
            if not isinstance(day_data, dict):
                continue
                
            available = day_data.get('availability', -1)  # Default to unavailable
            if available == 0:
                found_start = min(found_start, i)
                found_end = max(found_end, i)
            else:
                if found_end - found_start + 1 >= min_required_range:
                    return found_start, found_end + 1
                found_start, found_end = DEFAULT_MAX_RANGE, -1

        # Final check
        if found_end - found_start + 1 >= min_required_range:
            return found_start, found_end + 1
        return None

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
        startDate = self.date2str(start)
        endDate = self.date2str(end)
        url = f'{self.store.get('url')}/create-booking/results?mapId={mapId}&searchTabGroupId=0&bookingCategoryId=0&startDate={startDate}&endDate={endDate}&nights={end - start}&isReserving=true&equipmentId=-32768&subEquipmentId={self.store.get('equipment')}&peopleCapacityCategoryCounts=%5B%5B-32767,null,1,null%5D%5D&searchTime={c_time}&flexibleSearch=%5Bfalse,false,null,1%5D&filterData=%7B"-32756":"%5B%5B1%5D,0,0,0%5D"%7D'
        if resourceLocationId:
            url += f"&resourceLocationId={resourceLocationId}"
        return url

    def search(self, map_id) -> bool:

        if map_id == "-2147483403" or map_id == -2147483403: # ignore Jasper Overflow
            return False

        days = self.store.get('days')

        response = self.api_check(0, days , map_id)

        if response is None :
            print(f"Request Error {map_id}")
            return False
        
        try:
            mapLinkAvailabilities = response.get('mapLinkAvailabilities')
            resourceAvailabilities = response.get('resourceAvailabilities')

            if resourceAvailabilities:
                for site_id, available in resourceAvailabilities.items():
                    if available[0]['availability'] == 7 or available[0]['availability'] == 0:
                        self.site_list.append(site_id)
            else :
                for child_map_id, available in mapLinkAvailabilities.items():
                    # if available[0] == 0 or available[0] == 7 or available[0] == 3: # available or partly available
                        self.search(child_map_id)

        except Exception as e:
            _debug_print(f"Search-Error {e}")

    def run(self):
        """
        Run the scraper to find available date ranges.
        This method will create threads for each range found and wait for them to complete.
        """

        # time log
        _start_time = time.time()

        # create session
        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")
        self._init_session_()

        _debug_print(
            f"Starting session :  {current_time}",
            "\n------------------------------\n",
        )

        days = self.store.get('days')
        parks = self.store.get('location')

        self.site_list = []
        search_results = {
            "time" : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data" : []
        }
        push_results = 0

        for park_id in parks:
            self.search(park_id)

        _debug_print(f"Found {len(self.site_list)} sites available...", self.site_list)

        for resource_id in self.site_list:
            resource = self.store.fetch_one('resource_map', 'id = ?', (resource_id,))

            if resource is None:
                _debug_print(f"Resource #{resource_id} not exist in the database..")

            found_range = self.find_availability(0, days, resource['id'])
            if found_range:
                push_results += 1
                booking_url = self.make_booking_url(resource['map_id'], found_range[0], found_range[1], resource['location_id'])
                location = self.store.find_location(resource['location_id'])
                
                search_results["data"].append({
                    "id"   : resource['id'],
                    "site" : resource['name'],
                    "img_url" : json.loads(resource['photos']),
                    "full_name" : location['full_name'],
                    "attributes" : json.loads(resource['attr'].decode('utf-8')),
                    "category" : resource['category'],
                    "description" : resource['description'],
                    "start_date" : self.date2str(found_range[0]),
                    "end_date" : self.date2str(found_range[1]),
                    "capacity" : resource['capacity'],
                    "booking_url" : booking_url,
                    "added_to_cart" : False
                })

        _debug_print(
            f"Running Time: {time.time() - _start_time:.2f} seconds, API Calls : {self.api_calls}"
        )

        self._del_session_()

        self.store.flush("searchResult", search_results)
        
        self.send_push(
            f"PARKS CANADA ALERT ({search_results['time']})",
            f"""
                Available Sites Found : {push_results}
            """,
        )

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

    input('Press Enter...')