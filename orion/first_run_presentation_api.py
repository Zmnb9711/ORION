from fastapi import APIRouter, Query

from orion.first_run_presentation import UiLanguage, WizardPresentation, get_first_run_presentation


router = APIRouter(prefix="/v1/first-run", tags=["First Run Wizard"])


@router.get("/presentation", response_model=WizardPresentation)
def first_run_presentation(language: UiLanguage = Query(default=UiLanguage.EN)) -> WizardPresentation:
    return get_first_run_presentation(language)
