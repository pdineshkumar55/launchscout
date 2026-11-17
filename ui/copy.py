"""Every user-visible string in the app. Checked by scripts/check_ui_copy.py."""

APP_TITLE = "LaunchScout"
PAGE_ICON = "🔍"
TAGLINE = "Know your market before you launch."
INTRO = (
    "Enter a business idea and a city. LaunchScout finds local competitors, their prices and what "
    "customers say about them, then suggests a position, a launch price and a 30-day plan. "
    "Every price and claim links to its source."
)

# Form
FORM_HEADER = "Your idea"
IDEA_LABEL = "Business idea"
IDEA_PLACEHOLDER = "e.g. Healthy millet meal boxes"
CITY_LABEL = "City"
CITY_PLACEHOLDER = "e.g. Coimbatore"
TARGET_LABEL = "Target customer"
TARGET_PLACEHOLDER = "e.g. Office workers and health-conscious families"
OWN_BUSINESS_LABEL = "Your business (optional)"
OWN_BUSINESS_PLACEHOLDER = "Your shop or brand name. It is left out of the competitor list."
OWN_BUSINESS_HELP = ("Fill this in if you already run a business in this city, so your own shop is not "
                     "reported as a competitor.")
COMPETITORS_LABEL = "Known competitors (optional)"
COMPETITORS_HELP = "Comma-separated. These names are included in the search."
MORE_OPTIONS = "More options"
COUNTRY_LABEL = "Country"
CURRENCY_LABEL = "Currency"
START_BUTTON = "Start research"
SAMPLE_BUTTON = "Try with sample data"
NEW_BUTTON = "New research"
RUN_TIME_NOTE = "A run usually takes 1 to 3 minutes."

ERR_IDEA = "Enter a business idea (3 to 200 characters)."
ERR_CITY = "Enter a city."
ERR_FIELD_TOO_LONG = "One of the fields is too long. Please shorten it."

# How it works (shown before the first run)
HOW_HEADER = "How it works"
HOW_STEPS = [
    ("🔍", "Market scan", "Finds 3 to 5 competitors in your city with prices, offers and sales channels."),
    ("📝", "Customer feedback", "Collects what customers praise and complain about on review sites."),
    ("📈", "Gap & positioning", "Compares competitors and recommends a position and a launch price."),
    ("✅", "Report", "Writes a short report with a 30-day launch plan and a numbered source list."),
]

# Progress
PROGRESS_HEADER = "Research progress"
ELAPSED = "Elapsed: {minutes}m {seconds:02d}s"
STATUS_WAITING = "Waiting"
STATUS_RUNNING = "Running"
STATUS_DONE = "Done"
LOG_HEADER = "Activity"
LOG_EMPTY = "Starting…"
SCREENING = "Checking your request…"

# Results
RESULTS_HEADER = "Report: {label}"
TAB_REPORT = "Report"
TAB_COMPETITORS = "Competitors"
TAB_SOURCES = "Sources"
TAB_DOWNLOADS = "Downloads"
COL_COMPETITOR = "Competitor"
COL_PRICE = "Price"
COL_PRICE_CHECK = "Price check"
COL_CHANNELS = "Channels"
COL_TYPE = "Type"
COL_SOURCE = "Source"
PRICE_CONFIRMED = "Confirmed on source"
PRICE_NOT_CONFIRMED = "Not confirmed on source"
PRICE_NOT_LISTED = "Not listed"
SOURCES_CAPTION = "Every source cited in the report."
SOURCES_EMPTY = "No sources were recorded for this report."
DOWNLOAD_MD = "Download Markdown"
DOWNLOAD_PDF = "Download PDF"
DOWNLOAD_HELP = "Files are named after your idea and city."
PDF_UNAVAILABLE = "The PDF could not be created for this report. The Markdown file has the same content."
FOOTER = "Based on publicly available information. Verify prices before making decisions."

# Sidebar
PAST_HEADER = "Past reports"
PAST_EMPTY = "No reports yet."
PAST_NOTE = "Saved report from {date}."
SAMPLE_NOTE = "This is a sample report. Start a new run to research your own idea."

# Access code
ACCESS_HEADER = "Enter access code"
ACCESS_LABEL = "Access code"
ACCESS_BUTTON = "Continue"
ACCESS_WRONG = "That code is not right."

# Limits and errors (neutral; never show technical details)
DAILY_LIMIT = "Daily limit reached. Please try again tomorrow."
SESSION_LIMIT = "You have reached the limit of reports for this session. Please come back later."
BUSY = "The service is busy right now. Please try again in a few minutes."
ALREADY_RUNNING = "A report is already being prepared. Please wait for it to finish."
REFUSED = "We can't research this request."
NOT_CONFIGURED = "The service is not set up yet. Please try again later."
ERROR_GENERIC = "Something went wrong and the research could not finish. Please try again."
SEARCH_DOWN = "Web search is not available right now. Please try again later."
TIMEOUT_PARTIAL = ("The research took longer than expected. The report below covers what was found "
                   "before it stopped.")
PARTIAL = "The research stopped early. The report below covers what was found."
