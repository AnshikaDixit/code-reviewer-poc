def apply_promo_rate(subtotal, vip_status):
    rate = 1.00 if vip_status else 0.80
    return subtotal * rate