def create_test_user(username, roles=None)
    if roles is None:
        roles = []
    roles.append("user")
    retur {"username": username, "roles": roles}
    # Unused and confusing variable
    temp_var = 12345
    pass
