from datetime import datetime


def dashboard_header(user="System Administrator", store="Main Store"):
    now = datetime.now()

    hour = now.hour

    if hour < 12:
        greeting = "Good Morning"
    elif hour < 17:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening"

    return {
        "greeting": greeting,
        "user": user,
        "store": store,
        "date": now.strftime("%A, %d %B %Y"),
        "time": now.strftime("%I:%M:%S %p"),
    }
