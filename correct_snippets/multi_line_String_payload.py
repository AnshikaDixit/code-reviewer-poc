def create_error_manifest(code, system_id):
    report = f"SYS-ERR: {code}\n" + \
             f"LOCATION: {system_id}"
    return report