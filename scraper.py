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


load_dotenv()
PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("on", "1", "t")


def _debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

class Store:
    def __init__(self):
        self.data = {
            "url": "https://reservation.pc.gc.ca",
            "rootMapId" : "-2147483575",
            "westernMapId" : "-2147483574",
            "map": {"rootId": -2147483575, "westernId": -2147483574, "root": {}},
            "api": {},
            "rootMap" : {},
            "resourceLocation": {},
            "equipment": {},
            "search_setting" : {},
            "search_result" : {},
            "cart" : {}
        }

    def get(self, key: str):
        """
        Get a value from the store by key.
        If the key does not exist, it returns None.
        """
        if key in self.data:
            if not self.data[key]:
                self._load_(key)
            return self.data[key]
        return None

    def set(self, key : str, value):
        """
        Set a value in the store by key.
        If the key already exists, it updates the value.
        """
        if key not in self.data:
            self.data[key] = dict()

        if self.data[key] != value:
            self.data[key] = value
            self._flush_(key)

    def _flush_(self, key):
        if key in self.data:
            try:
                with open(f"store/{key}.json", "w", encoding="utf-8") as fp:
                    json.dump(self.data[key], fp, indent=4)
            except Exception as e:
                _debug_print(f"Error while flush! {e}")
    
    def _load_(self, key):
        if key in self.data:
            try:
                with open(f"store/{key}.json", "r", encoding="utf-8") as fp:
                    self.data[key] = json.load(fp)
            except : #noqa : E722
                self.data[key] = dict()

class Scraper:
    def __init__(self):
        # initialize
        self.home_url = os.getenv("HOME_URL", "https://reservation.pc.gc.ca")

        self.store = Store()
        self.api_calls = 0
        self.search_result = None

        # Initialize task scheduler
        self.lock = threading.Lock()
        self.is_running = False
        self.process = None
        self.running_interval = 20

        # Initialize Search Setting
        self.current_location = None
        self.equipment = "Trailer or Motorhome over 35pt"
        self.date_range = 60

        # Initialize Firebase Cloud Messaging
        self.fcm_token = os.getenv("FCM_TOKEN")
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)

    def _date_str_(self, days_from_today: int) -> str:
        """
        Get the date string in 'YYYY-MM-DD' format for a given number of days from today.
        """
        target_date = self.today + timedelta(days=days_from_today)
        return target_date.strftime("%Y-%m-%d")

    def make_url(self, mapId: str, startDate: date, endDate: date, resourceLocationId: str = None):
        now = datetime.now()
        c_time = (
            now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(now.microsecond / 1000):03d}"
        )

        delta = endDate - startDate
        url = f"{self.home_url}/create-booking/results?mapId={mapId}&searchTabGroupId=0&bookingCategoryId=0&startDate={startDate.days}&endDate={endDate.days}&nights={delta.days}&isReserving=true&equipmentId={self.equipmentId}&subEquipmentId=-32759&peopleCapacityCategoryCounts=%5B%5B-32767,null,1,null%5D%5D&searchTime={c_time}&flexibleSearch=%5Bfalse,false,null,1%5D&filterData=%7B%7D"
        if resourceLocationId:
            url += f"&resourceLocationId={resourceLocationId}"
        return url

    def _init_session_(self):
        # Initialize Selenium Web Driver
        options = Options()
        options.add_argument("--headless")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )
        self.driver.get(self.home_url)
        self.driver.maximize_window()
        time.sleep(5)
        self.cart_uid = self.driver.execute_script(
            "return localStorage.getItem('cartUid');"
        )
        self.cart_transaction_uid = self.driver.execute_script(
            "return localStorage.getItem('cartTransactionUid');"
        )
        # init request
        self.session = requests.Session()
        self.headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Origin": "https://reservation.pc.gc.ca",
            "Referer": self.home_url,
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
        self.search_result = dict()

    def _del_session_(self):
        self.driver.quit()
        self.session.close()

    def _request(self, methods: str, url: str, headers=None, params=None, data=None):
        """
        Make a simple GET request to the specified URL.
        """

        time.sleep(1)

        if headers is None:
            headers = self.headers

        if methods == "GET":
            response = self.session.get(url, headers=headers, params=params)
        elif methods == "POST":
            response = self.session.post(url, headers=headers, params=params, data=data)
        else:
            _debug_print(f"Unsupported method: {methods}")
            return None

        self.api_calls += 1

        if response.status_code == 200:
            return response.json()
        else:
            _debug_print(f"Request failed with status code: {response.status_code}")
            return None

    def _api_check(self, start: int, end: int, mapId=None):
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

        startDate = (self.today + timedelta(start)).strftime("%Y-%m-%d")
        endDate = (self.today + timedelta(end)).strftime("%Y-%m-%d")
        utc_time = (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        )
        xsrf_token = self.session.cookies.get("XSRF-TOKEN", "")

        data = self._request(
            methods="GET",
            url=f"{self.home_url}/api/availability/map",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "App-language": "en-CA",
                "App-version": "5.98.197",
                "Cache-Control": "no-cache",
                "Dnt": "1",
                "Expires": "0",
                "Pragma": "no-cache",
                "Referer": self.home_url,
                "Request-Id": f"|{uuid.uuid4()}.{uuid.uuid4().hex[:12]}",
                "Sec-CH-UA": '"Microsoft Edge";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"Windows"',
                "Traceparent": f"00-{uuid.uuid4().hex[:32]}-{uuid.uuid4().hex[:16]}-01",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "X-XSRF-TOKEN": xsrf_token,
            },
            params={
                "mapId": mapId,
                "bookingCategoryId": 0,
                "equipmentCategoryId": -32768,
                "subEquipmentCategoryId": -32759,
                "cartUid": self.cart_uid,  # Update with current session value
                "cartTransactionUid": self.cart_transaction_uid,  # Update with current session value
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
                "seed": utc_time,
            },
        )

        if (
            data is None
            or "mapAvailabilities" not in data
            or data.get("mapAvailabilities")[0] > 0
        ):
            _debug_print(f"API Call #{self.api_calls}: {startDate} - {endDate} -> F")
            return None
        else:
            _debug_print(f"API Call #{self.api_calls}: {startDate} - {endDate} -> T")
            return data

    def find_available_ranges(self, min_block=5):
        total_days = self.date_range
        self.api_calls = 0
        ranges = []
        day = 0

        def expand_window(start):
            low = min_block
            high = total_days - start
            best_end = start + min_block - 1
            # Binary search for maximum available window
            while low <= high:
                mid = (low + high) // 2
                if self._api_check(start, start + mid - 1):
                    best_end = start + mid - 1
                    low = mid + 1
                else:
                    high = mid - 1
            return best_end

        while day <= total_days - min_block:
            # First check if a large block is available
            if self._api_check(day, day + min_block - 1):
                end = expand_window(day)
                ranges.append((day, end))
                day = end + 1  # Jump past this block
            else:
                day += 1  # Slide forward

        # debug print the found ranges
        _debug_print(f"Found {len(ranges)} available date ranges:")

        for start, end in ranges:
            start_date = self._date_str_(start)
            end_date = self._date_str_(end)
            _debug_print(f"Available range found: {start_date} to {end_date}")

        return ranges

    def handle_range(self, start: int, end: int, mapId=None, resourceLocationId=None):
        """
        Handle a range of dates by checking availability and printing results.
        """

        start_date = self._date_str_(start)
        end_date = self._date_str_(end)
        range_key = f"{start_date}-{end_date}"

        if mapId is None:
            mapId = self.store.get("westernMapId")

        if resourceLocationId is None:
            item = next(
                filter(
                    lambda x: str(x["rootMapId"]) == mapId,
                    self.store.get("resourceLocation"),
                ),
                None,
            )
            resourceLocationId = item.get("resourceLocationId") if item else None

        response = self._api_check(start, end, mapId)

        if (
            response is None
            or response.get("mapAvailabilities") is None
            or response.get("mapAvailabilities")[0] != 0
        ):
            _debug_print(
                f"No availability found in #Map - {mapId} for range: ({range_key})"
            )
            return

        mapLinkAvailabilities = response.get("mapLinkAvailabilities")
        resourceAvailabilities = response.get("resourceAvailabilities", {})

        # _debug_print(f">>> mapId: {mapId}, resourceLocationId: {resourceLocationId}, mapLinkAvailabilities: {mapLinkAvailabilities}, resourceAvailabilities: {resourceAvailabilities} ")

        if mapLinkAvailabilities:
            if resourceAvailabilities:
                _debug_print("Unexpected resource availabilities found.")
                return
            for childmapId, availible in mapLinkAvailabilities.items():
                if availible[0] == 0:
                    self.handle_range(start, end, childmapId, resourceLocationId)
        else:
            if resourceLocationId:
                resources = self._request(
                    "GET",
                    f"{self.home_url}/api/resourcelocation/resources?resourceLocationId={resourceLocationId}",
                )
                for resourceId, available in resourceAvailabilities.items():
                    if available[0].get("availability") == 0:
                        _debug_print(
                            f"Resource #{resourceId} is available for range: ({range_key})"
                        )
                        self.search_result.update(
                            {resourceId: resources.get(resourceId, {})}
                        )

    def send_push(self, title, body):
        fcm_token = self.fcm_token
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

    def run(self):
        """
        Run the scraper to find available date ranges.
        This method will create threads for each range found and wait for them to complete.
        """

        _start_time = time.time()

        self._init_session_()

        max_range = 0
        start, end = 0, 0

        if self.current_location is None:
            available_ranges = self.find_available_ranges()
            for st, en in available_ranges:
                if max_range < en - st:
                    max_range = en - st
                    start, end = st, en
        else:
            pass

        start_date = self._date_str_(start)
        end_date = self._date_str_(end)
        range_key = f"{start_date}-{end_date}"

        _debug_print(
            f"Handling range: {start_date} to {end_date}",
            "\n------------------------------\n",
        )

        self.handle_range(start, end)

        _debug_print(
            f"Time: {time.time() - _start_time:.2f} seconds, API Calls : {self.api_calls}"
        )

        messageList = []
        store = self.store.get("resourceLocation")
        for resource_id, data in self.search_result.items():
            resourceLocation = None
            for x in store:
                if x["resourceLocationId"] == data["resourceLocationId"]:
                    resourceLocation = x
                    break

            if resourceLocation is None:
                continue

            localizedValues = resourceLocation.get("localizedValues")

            messageList.append(
                {
                    "id": resource_id,
                    "resource": localizedValues[0]["fullName"],
                    "description": localizedValues[0]["description"],
                    "drivingDirection": localizedValues[0]["drivingDirections"],
                    "site": data["localizedValues"][0]["name"],
                    "capacity": data["maxCapacity"],
                    "url": localizedValues[0]["website"],
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )

        self.search_result = messageList

        if self.store.get('search_result') == self.search_result:
            return
        else :
            self.store.set("search_result", self.search_result)

        self.send_push(
            f"PARK Notification ({datetime.now()})",
            f"""
                Available Dates : {range_key}
                Sites Found : {len(self.search_result)}
            """,
        )

        self._del_session_()

    def start(self):
        with self.lock:
            if self.process is not None:
                self.process.cancel()
            self.is_running = True
            self.run()
            self.process = threading.Timer(self.running_interval * 60, self.start)
            self.process.start()

    def stop(self):
        with self.lock:
            self.is_running = False
            if self.process is not None:
                self.process.cancel()
                self.process = None

    def set_fcm_token(self, token):
        with self.lock:
            if token and self.fcm_token != token:
                self.fcm_token = token
                set_key(PATH, "FCM_TOKEN", token)

    def setting(self, location: str, equipement: str, date_range: int, interval: int):
        self.running_interval = int(interval)
        self.date_range = int(date_range)
        self.equipment = equipement
        self.current_location = location
        # self.stop()
        # self.start()

    def put_cart(self, new_cart):
        all_carts = self.store.get("cart")
        results = self.store.get("search_result")

        new_carts = [cart for cart in all_carts if cart["id"] != new_cart["id"]]
        new_carts.append(new_cart)

        for i in range(len(results)):
            if results[i]['id'] == new_cart['id']:
                results[i]['added_to_cart'] = True
                break

        self.store._flush_("search_result")
        self.store.set("cart", new_carts)

    def delete_cart(self, cart_id):
        all_carts = self.store.get('cart')
        
        if cart_id == 'all':
            new_carts = []
        else :
            new_carts = [cart for cart in all_carts if cart["id"] != cart_id]

        search_results = self.store.get('search_result')
        for i in range(len(search_results)):
            if search_results[i]['id'] == cart_id:
                search_results[i].update({'added_to_cart' : False})
        self.store._flush_('search_result')
        self.store.set('cart', new_carts)


if __name__ == "__main__":
    scraper = Scraper()
    # response = scraper.test_request(
    #     "https://reservation.pc.gc.ca/api/availability/map?mapId=-2147483575&bookingCategoryId=0&equipmentCategoryId=-32768&subEquipmentCategoryId=-32765&cartUid=&cartTransactionUid=&bookingUid=&groupHoldUid=&startDate=2025-06-30&endDate=2025-07-01&getDailyAvailability=false&isReserving=true&filterData=%5B%5D&boatLength=0&boatDraft=0&boatWidth=0&peopleCapacityCategoryCounts=%5B%7B%22capacityCategoryId%22:-32767,%22subCapacityCategoryId%22:null,%22count%22:1,%22isAdult%22:null%7D%5D&numEquipment=0&seed=2025-06-30T16:58:29.415Z"
    # )
    scraper.run()

    input("Press Enter to exit...")
