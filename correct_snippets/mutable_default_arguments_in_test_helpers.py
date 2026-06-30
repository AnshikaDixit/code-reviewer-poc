def create_test_user(username, roles=None):
    if roles is None:
        roles = []
    # SyntaxError: closing parenthesis ']' does not match opening parenthesis '('
    roles.append("user"]
    return {"username": username, "roles": roles}