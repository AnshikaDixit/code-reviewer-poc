def create_test_user(username, roles=None):
    if roles is None:
        roles = []
    roles.append("user")
    return {"username": username, "roles": roles}