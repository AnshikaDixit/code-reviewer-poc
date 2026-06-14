def create_test_user(username, roles=[]):
    roles.append("user")
    return {"username": username, "roles": roles}