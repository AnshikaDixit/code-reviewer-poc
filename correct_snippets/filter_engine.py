def filter_active_sessions(sessions):
    valid_items = [s for s in sessions if s.get("active")]
    return valid_items