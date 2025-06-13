import os, time
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

driver = None # selenium chrome web driver
wait = None # web driver wait

def init():
    global driver, wait

    # Set up Chrome options
    chrome_options = Options()
    # chrome_options.add_argument("--headless")  # Run in headless mode (no GUI)
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # Initialize the Chrome WebDriver
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
    wait = WebDriverWait(driver, 10)

    load_dotenv()
    url = os.getenv('URL')
    driver.get(url)

    # Set implicit wait time
    time.sleep(5)  # Wait for the page to load

def select_option(dropdown_id, equipment_text):
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
        if "Trailer or Motorhome over 35ft" in opt.text:
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
    purple_dots = driver.find_elements(By.CSS_SELECTOR, ".leaflet-marker-icon.icon-partial")
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
            wait.until(lambda d: d.find_element(By.ID, "resourceName").text != current_site)
        else :
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
        wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "mat-mdc-dialog-container")))
        time.sleep(3)  # Wait for calendar to load or UI update
    except Exception as e:
        print(f"Error in click_calendar_button : {e}")

def get_available_dates():
    global driver, wait
    available_dates = []
    try:
        site_name = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "site-title"))).text
        day_cells = driver.find_elements(By.CSS_SELECTOR, "td.day-cell")
        for i, td in enumerate(day_cells):
            icons = td.find_elements(By.CSS_SELECTOR, "fa-icon > svg.fa-check")
            if icons :
                date = td.get_attribute("data-e2e-date") or td.get_attribute("aria-label") or td.text
                available_dates.append(date.strip())
            else :
                continue
        print(f"Site {site_name} available nights: {available_dates}")
    except Exception as e:
        print(f"Error in get_available_dates : {e}")
    return available_dates

def close_site_calendar():
    global driver, wait
    try :
        close_button = driver.find_element(By.ID, "cancelButton")
        close_button.click()
        time.sleep(1)  # Wait for the modal to close
    except Exception as e:
        print(f"Could not close calendar modal: {e}")

def main():
    select_option("equipment-field", "Trailer or Motorhome over 35ft")
    click_search_button("actionSearch")
    purple_dots = find_purple_dots()
    for dot in purple_dots:
        click_purple_dot(dot)
        open_site_calendar()
        get_available_dates()
        close_site_calendar()

if __name__ == '__main__':
    init()
    main()
    input('Press Enter to close the browser...')