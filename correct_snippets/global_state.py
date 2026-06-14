TAX_RATE = 0.05

def calculate_price(item_price):
    global TAX_RATE
    return item_price * (1 + TAX_RATE)  # Highly fragile for parallel testing or shifting global scopes