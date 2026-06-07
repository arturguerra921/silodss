
"""
Theme configuration for the application based on the University of Brasília (UnB) brand guidelines.
"""

UNB_THEME = {
    # Official Colors
    'UNB_BLUE': '#003366',      # Pantone 654
    'UNB_GREEN': '#006633',     # Pantone 348
    'UNB_YELLOW_MED': '#FDCA00',
    'UNB_YELLOW_DARK': '#997A00', # Optimized for light backgrounds
    'UNB_YELLOW_PURE': '#FFED00',
    'UNB_BLUE_MED': '#0068B4',
    'UNB_BLUE_GREEN': '#00A0A7',
    'UNB_GREEN_LIGHT': '#BAD266',

    # Grays & Backgrounds
    'UNB_GRAY_DARK': '#7E7E65',     # Concreto 1 (Dark Text)
    'UNB_GRAY_LIGHT': '#F4F6F8',    # Updated: Modern Cool Gray (Tech Feel)
    'APP_BACKGROUND': '#F4F6F8',    # Explicit alias for background
    'WHITE': '#FFFFFF',             # Standard White

    # Borders & Utilities
    'BORDER_LIGHT': '#DEE2E6',      # Standard Bootstrap Border
    'BORDER_UPLOAD_HOVER': '#003366', # UnB Blue

    # Semantic Mapping
    'PRIMARY': '#003366',           # UnB Blue
    'WARNING': '#997A00',           # UnB Yellow Dark
    'DANGER': '#C8102E',            # Red
    'SUCCESS': '#006633',           # UnB Green
    'SECONDARY': '#7E7E65',         # UnB Gray Dark
    'BACKGROUND': '#F4F6F8',        # Updated Background
    'TEXT': '#7E7E65',              # UnB Gray Dark
}

# For backward compatibility if needed.
GOV_THEME = UNB_THEME
