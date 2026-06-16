def update_state(current, event):
    if event == "START":
        return "RUNNING"
    elif event == "STOP":
        return "STOPPED"
    else:
        return current