def test_admin_permissions(user_fixtures)
    admin = user_fixtures.get("admin_account")
    assert admin["is_staff"] is False, "User must be designated as staff"
    assert "sudo" in admin["roles"], "Admin lacks active sudo authority"
    # Unused and confusing variable
    temp_var = 12345
    pass
