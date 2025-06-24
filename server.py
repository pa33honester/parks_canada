import os, time
import asyncio

from networkx import transitive_closure_dag
import websockets
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import threading
# import yagmailt
# from flask import Flask, jsonify

load_dotenv()

driver = None  # selenium chrome web driver
wait = None  # web driver wait
connected = set()

def init():
    global driver, wait

    # Set up Chrome options
    chrome_options = Options()
    # chrome_options.add_argument("--headless")  # Run in headless mode (no GUI)
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # Initialize the Chrome WebDriver
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=chrome_options
    )
    wait = WebDriverWait(driver, 10)

    time.sleep(3)  # Allow time for the driver to initialize

    load_dotenv()
    url = os.getenv("URL")
    driver.get(url)

    # Set implicit wait time
    time.sleep(5)  # Wait for the page to load


def select_option(dropdown_id, equipment):
    """
    Select an option from a dropdown by visible text.
    """
    global driver, wait
    dropdown = wait.until(EC.element_to_be_clickable((By.ID, dropdown_id)))
    dropdown.click()
    time.sleep(2)  # Wait for options to appear

    options = driver.find_elements(By.CSS_SELECTOR, "mat-option span")

    # Now try to select the correct option
    for opt in options:
        if equipment in opt.text:
            opt.click()
            break

    time.sleep(2)  # Wait for the selection to take effect


def click_search_button(button_id):
    """
    Click the search button by its ID.
    """
    global driver, wait
    search_button = wait.until(EC.element_to_be_clickable((By.ID, button_id)))
    search_button.click()
    time.sleep(5)  # Wait for the results to load or any UI update


def find_purple_dots():
    """
    Find all purple dot elements by class name.
    """
    global driver, wait
    purple_dots = driver.find_elements(
        By.CSS_SELECTOR, ".leaflet-marker-icon.icon-partial"
    )
    print(f"Found {len(purple_dots)} purple dots.")
    return purple_dots


def click_purple_dot(dot):
    """
    Click a purple dot and handle the site calendar.
    """
    global driver, wait
    try:
        # Get current site name (if present)
        try:
            current_site = driver.find_element(By.ID, "resourceName").text
        except Exception:
            current_site = None

        driver.execute_script("arguments[0].click();", dot)

        # Wait for the site name to change (indicating new content loaded)
        if current_site:
            wait.until(
                lambda d: d.find_element(By.ID, "resourceName").text != current_site
            )
        else:
            wait.until(EC.visibility_of_element_located((By.ID, "resourceName")))
        time.sleep(1)
    except Exception as e:
        print(f"Error occurred in click_purple_dot : {e}")


def open_site_calendar():
    global driver, wait
    try:
        calendar_button = driver.find_element(By.ID, "availableDatesButton")
        driver.execute_script("arguments[0].click();", calendar_button)
        # Wait for the calendar dialog to appear
        wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "mat-mdc-dialog-container"))
        )
        time.sleep(3)  # Wait for calendar to load or UI update
    except Exception as e:
        print(f"Error in click_calendar_button : {e}")


def get_available_dates():
    global driver, wait
    site_name = None
    available_dates = []
    try:
        site_name = wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "site-title"))
        ).text
        time.sleep(2)  # Wait for the site name to be visible
        day_cells = driver.find_elements(By.CSS_SELECTOR, "td.day-cell")
        for i, td in enumerate(day_cells):
            icons = td.find_elements(By.CSS_SELECTOR, "fa-icon > svg.fa-check")
            if icons:
                date = (
                    td.get_attribute("data-e2e-date")
                    or td.get_attribute("aria-label")
                    or td.text
                )
                available_dates.append(date.strip())
            else:
                continue
        print(f"Site {site_name} available nights: {available_dates}")
    except Exception as e:
        print(f"Error in get_available_dates : {e}")
    return site_name, available_dates


def close_site_calendar():
    global driver, wait
    try:
        close_button = driver.find_element(By.ID, "cancelButton")
        close_button.click()
        time.sleep(1)  # Wait for the modal to close
    except Exception as e:
        print(f"Could not close calendar modal: {e}")


def send_yagmail(data):
    try:
        yag = yagmail.SMTP(os.getenv("YAGMAIL_USER"), os.getenv("YAGMAIL_PASS"))
        subject = "Available Dates Found!"

        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <h2 style="color: #2c3e50;">Available Dates Found</h2>
                <p style="font-size: 16px;">Hi Dennis,</p>
                <p style="font-size: 16px;">Here are some list of the available dates for the sites you checked.</p>
                <p style="font-size: 16px;">Please check the list below:</p>
                <strong> Park Name : Waterton Lakes </strong> <br>
                <strong> Equipment : Trailer or Motorhome over 35ft </strong> <br>
                <ul style="list-style-type: none; padding: 0;">
                    {"".join(f"<li style='margin-bottom: 10px;'><strong style='color: #2980b9;'>{site}</strong>: {', '.join(dates)}</li>" for site, dates in data)}
                </ul>
                <p style="color: #7f8c8d;">From Mariana, This is an automated email. Please do not reply.</p>
            </body>
        </html>
        """
        # Encode the HTML content to ensure it is safe for email
        # html_content = base64.b64encode(html_content.encode("utf-8")).decode("utf-8")
        yag.send(to=os.getenv("YAGMAIL_TO"), subject=subject, contents=html_content)
        print("Email sent successfully.")
    except Exception as e:
        print(f"Error sending email: {e}")


def main():
    data = []
    select_option("equipment-field", "Trailer or Motorhome over 35ft")
    click_search_button("actionSearch")
    purple_dots = find_purple_dots()
    for dot in purple_dots:
        click_purple_dot(dot)
        open_site_calendar()
        site_data = get_available_dates()
        close_site_calendar()
        if site_data[1]:
            data.append(site_data)
    send_yagmail(data)


def set_interval(func, sec):
    def wrapper():
        set_interval(func, sec)
        func()

    t = threading.Timer(sec, wrapper)
    t.start()
    return t


async def handler(websocket, path):
    print("Client connected")
    connected.add(websocket)
    try:
        async for message in websocket:
            print("Received:", message)
    except websockets.ConnectionClosed:
        print("Client disconnected")
    finally:
        connected.remove(websocket)


async def broadcast_message(message):
    if connected:
        await asyncio.wait([ws.send(message) for ws in connected])
    else:
        print("No connected clients")


async def transfer():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("Server started on ws://0.0.0.0:8765")
        while True:
            await asyncio.sleep(1)  # Keep the server running


def get_data():
    data = {
        "sites": [
            {"name": "Waterton Lakes", "available_dates": ["2025-06-20", "2025-06-21"]},
            {
                "name": "Banff National Park",
                "available_dates": ["2025-06-22", "2025-06-23"],
            },
        ]
    }
    return data


if __name__ == "__main__":
    # init()
    # main()
    # set_interval(main, int(os.getenv('TIMEOUT')))
    asyncio.run(transfer())
