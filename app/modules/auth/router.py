from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.core.dependencies import DbSession
from app.core.errors import AppError
from app.modules.auth import cookies, security, service
from app.modules.auth.dependencies import AuthSettings, CurrentUser, browser_request
from app.modules.auth.schemas import Credentials, CsrfResponse, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
browser = [Depends(browser_request)]


def token_response(grant: service.Grant, settings: AuthSettings, response: Response, csrf: str):
    access, lifetime = security.issue_access(
        settings, grant.user_id, grant.session_id, grant.expires_at
    )
    cookies.set_cookies(response, settings, grant.refresh_token, csrf, grant.expires_at)
    return TokenResponse(
        access_token=access,
        expires_in=lifetime,
        session_expires_at=grant.expires_at,
        csrf_token=csrf,
    )


@router.post("/signup", response_model=UserResponse, status_code=201, dependencies=browser)
def signup(body: Credentials, db: DbSession):
    return service.signup(db, str(body.email), body.password.get_secret_value())


@router.post("/login", response_model=TokenResponse, dependencies=browser)
def login(body: Credentials, db: DbSession, settings: AuthSettings, response: Response):
    grant = service.login(db, str(body.email), body.password.get_secret_value())
    return token_response(grant, settings, response, security.new_csrf(settings, grant.session_id))


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser):
    return user


@router.post("/csrf", response_model=CsrfResponse, dependencies=browser)
def csrf_bootstrap(request: Request, db: DbSession, settings: AuthSettings, response: Response):
    refresh_name, csrf_name = cookies.cookie_names(settings)
    session = service.csrf_bootstrap(db, request.cookies.get(refresh_name))
    csrf = request.cookies.get(csrf_name)
    try:
        security.verify_csrf(settings, session.id, csrf, csrf)
    except AppError:
        csrf = security.new_csrf(settings, session.id)
    cookies.set_cookies(response, settings, None, csrf, session.expires_at)
    return CsrfResponse(csrf_token=csrf)


@router.post("/refresh", response_model=TokenResponse, dependencies=browser)
def refresh(request: Request, db: DbSession, settings: AuthSettings, response: Response):
    refresh_name, csrf_name = cookies.cookie_names(settings)
    csrf = request.cookies.get(csrf_name)
    grant = service.refresh(
        db,
        settings,
        request.cookies.get(refresh_name),
        csrf,
        request.headers.get("X-CSRF-Token"),
    )
    if grant is None:
        # A normal outcome ensures the function-scoped get_db commits revocation
        # before emitting 401. Raising AppError here would roll it back.
        denied = JSONResponse(
            status_code=401,
            content={
                "code": "AUTH_REQUIRED",
                "message": "다시 로그인해주세요.",
                "details": None,
                "request_id": request.state.request_id,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
        cookies.clear_cookies(denied, settings)
        return denied
    return token_response(grant, settings, response, csrf)


@router.post("/logout", status_code=204, dependencies=browser)
def logout(request: Request, db: DbSession, settings: AuthSettings):
    refresh_name, csrf_name = cookies.cookie_names(settings)
    service.logout(
        db,
        settings,
        request.cookies.get(refresh_name),
        request.cookies.get(csrf_name),
        request.headers.get("X-CSRF-Token"),
    )
    response = Response(status_code=204)
    cookies.clear_cookies(response, settings)
    return response
