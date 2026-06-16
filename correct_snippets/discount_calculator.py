def apply_promo_rate(subtotal, vip_status):
    rate = 0.80 if vip_status else 1.00
    return subtotal * rate