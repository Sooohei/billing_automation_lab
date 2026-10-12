from fastapi import FastAPI


def create_app() -> FastAPI:
    return FastAPI(title="billing_automation_lab")


app = create_app()
