import logging
import os
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlsplit

from app.auth import (
    SESSION_COOKIE,
    AuthError,
    authenticate_password,
    change_password,
    clear_session_cookie,
    end_all_sessions,
    GoogleSignInError,
    end_session,
    register_user,
    request_password_reset,
    reset_password_with_code,
    resolve_session,
    set_session_cookie,
    sign_in_with_google,
    start_session,
)
from app import google_auth

from app.capture.image_extract import process_image_bytes, validate_image_upload
from app.capture.pdf_extract import extract_pdf_text, validate_pdf_upload
from app.capture.storage import (
    read_stored_bytes,
    resolve_storage_path,
    store_audio_bytes,
    store_image_bytes,
    store_pdf_bytes,
    store_thumbnail_bytes,
    thumbnail_relative_path,
)
from app.capture.url_fetch import fetch_url, validate_public_http_url
from app.capture.link_card import build_card, fetch_oembed, read_page, tidy_url, video_site
from app.capture.voice_extract import process_voice_bytes, validate_audio_upload
from app.database import (
    NotAuthenticatedError,
    add_image_item_to_db,
    create_manual_task,
    add_item_to_db,
    add_note_to_db,
    add_pdf_item_to_db,
    add_url_item_to_db,
    add_voice_item_to_db,
    complete_image_item_processing,
    complete_pdf_item_processing,
    complete_voice_item_processing,
    complete_analysis_run,
    complete_item_in_db,
    complete_url_item_processing,
    claim_item_for_retry,
    confirm_task_timing,
    TopicConflictError,
    create_topic_in_db,
    delete_topic_in_db,
    get_topic_deletion_plan,
    delete_item_from_db,
    delete_note_from_db,
    dismiss_relation_in_db,
    fail_analysis_run,
    fail_item_processing,
    get_attention_board,
    get_daily_briefing,
    get_item_from_db,
    get_item_insight,
    get_latest_successful_analysis,
    get_note_from_db,
    get_organization_dashboard,
    init_db,
    list_calendar_events_from_db,
    list_items_from_db,
    get_notification_settings,
    list_notes_from_db,
    list_relations_from_db,
    require_owner_id,
    list_tasks_from_db,
    get_topic_detail,
    list_item_updates,
    glance_rows,
    list_topics_from_db,
    owns_topic,
    list_bots_from_db,
    item_ids_for_bot,
    topic_name_exists,
    mark_item_processing,
    save_calendar_receipt,
    set_task_reminder_in_db,
    save_notification_settings,
    save_push_subscription,
    remove_push_subscription,
    set_task_date,
    set_task_priority,
    set_task_status,
    snooze_task_in_db,
    start_analysis_run,
    update_item_extracted_text,
    update_item_in_db,
    update_item_insight_overrides,
    update_task_in_db,
    update_note_in_db,
    update_topic_in_db,
)
from app.integrations.calendar import (
    CalendarWriteBlockedError,
    get_calendar_adapter,
    get_draft,
    store_draft,
)
from app.organizer import (
    analyze_inbox_with_openai,
    reassign_notes_to_topics,
    suggest_parent_topic,
    validate_analysis_result,
)
from app.retrieval.ask import build_grounded_answer
from app.retrieval.search import search_passages
from app.sensitive import mask_secrets
from app.schemas import (
    AuthUser,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    PasswordChangeRequest,
    RegisterRequest,
    ResetPasswordRequest,
    AskRequest,
    AskResponse,
    CalendarConfirmRequest,
    CalendarEvent,
    CalendarPreviewRequest,
    ExtractedTextUpdate,
    InboxItem,
    InboxItemCreate,
    InboxItemUpdate,
    InsightOverrideUpdate,
    ItemInsight,
    ItemRelation,
    Note,
    NoteCreate,
    NoteUpdate,
    NotificationPreferencesUpdate,
    PersistedAnalysis,
    Priority,
    PushSubscriptionRequest,
    SearchHit,
    Task,
    TaskCreate,
    TaskDateChange,
    TaskDateUpdate,
    TaskPriorityUpdate,
    TaskListStatus,
    TaskReminderRequest,
    TaskSnoozeRequest,
    TaskTimingConfirm,
    LifeBot,
    NeedsYouList,
    NeedsYouResolve,
    TaskIdea,
    AccountDeleteRequest,
    OnboardingAnswers,
    BotSummary,
    Greeting,
    ItemContextResult,
    ItemContextUpdate,
    ScoutAnswer,
    ScoutBulk,
    ScoutResult,
    ScoutState,
    TaskSomeday,
    MemoryFact,
    MemoryUpdate,
    MemoryView,
    UserSettings,
    UserSettingsUpdate,
    ResortPlan,
    ResortResult,
    TopicMovesUndo,
    TopicRecheck,
    TaskUpdate,
    Topic,
    TopicDetail,
    Glance,
    TopicCreate,
    TopicDeleteResult,
    TopicParentSuggestion,
    TopicParentSuggestionRequest,
    TopicUpdate,
    UrlItemCreate,
)
from app.schemas import NOTE_MAX_LENGTH
from app.bots import BOT_KEYS, BOTS
import app.captain as captain
import app.filing as filing


from contextlib import asynccontextmanager

APP_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def _check_startup_health():
    from app.config import load_config

    config = load_config(strict=False)
    if not config.nvidia_api_key:
        logger.warning(
            "⚠️ NVIDIA_API_KEY is not set. Life Inbox is running in offline mode: "
            "using deterministic organization and extractive retrieval. "
            "Add NVIDIA_API_KEY to .env for NVIDIA NIM LLM analysis and ASR voice transcription."
        )

    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from app.database import engine

        alembic_ini_path = APP_DIR.parent / "alembic.ini"
        if alembic_ini_path.exists() and os.getenv("LIFE_INBOX_AUTO_CREATE_TABLES") != "1":
            alembic_cfg = Config(str(alembic_ini_path))
            script = ScriptDirectory.from_config(alembic_cfg)
            head_rev = script.get_current_head()

            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()

            if current_rev != head_rev:
                logger.warning(
                    "⚠️ Database migrations are pending (current: %s, head: %s). "
                    "Run 'alembic upgrade head' to bring your database schema up to date.",
                    current_rev,
                    head_rev,
                )
    except Exception as e:
        # Was debug-level, which hid a NameError (missing `os` import) for a
        # long time. Keep it non-fatal but visible.
        logger.warning("Startup migration check skipped: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_startup_health()
    yield


app = FastAPI(title="Life Inbox", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

init_db()


PUBLIC_PATHS = frozenset(
    {
        "/login",
        "/privacy",
        "/terms",
        "/api/health",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/password/forgot",
        "/api/auth/password/reset",
        "/api/auth/providers",
        "/api/auth/google/start",
        "/auth/google/callback",
        "/service-worker.js",
    }
)
PUBLIC_PREFIXES = ("/static/",)
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def _is_cross_site_write(request: Request) -> bool:
    """Block state-changing API calls that come from another site."""
    if request.method not in UNSAFE_METHODS:
        return False
    if request.headers.get("sec-fetch-site") == "cross-site":
        return True
    origin = request.headers.get("origin")
    if not origin:
        return False
    host = request.headers.get("host", "")
    return urlsplit(origin).netloc.lower() != host.lower()


def _apply_security_headers(request: Request, response: Response) -> None:
    from app.config import load_config

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Referrer-Policy", "strict-origin-when-cross-origin"
    )
    path = request.url.path
    if path.startswith("/api/") or path in {"/", "/login"}:
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith("/static/"):
        # Revalidate on every load (cheap 304 via ETag) so a browser never
        # runs an old script against a newer page after an update.
        response.headers.setdefault("Cache-Control", "no-cache")
    if load_config(strict=False).environment in {"beta", "production"} or \
            os.getenv("LIFE_INBOX_SECURE_COOKIES", "").strip() == "1":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Every route except the public ones needs a valid session.

    Logged-out API calls get 401; logged-out page loads go to /login.
    """
    from app.database import set_current_owner_id

    path = request.url.path
    if path.startswith("/api/") and _is_cross_site_write(request):
        response = JSONResponse(
            {"detail": "Cross-site request blocked."}, status_code=403
        )
        _apply_security_headers(request, response)
        return response

    token = request.cookies.get(SESSION_COOKIE)
    user = await run_in_threadpool(resolve_session, token) if token else None
    request.state.user = user

    if user is None and not _is_public_path(path):
        if path.startswith("/api/"):
            response = JSONResponse(
                {"detail": "Authentication required."}, status_code=401
            )
        else:
            response = RedirectResponse("/login", status_code=302)
        if token:
            clear_session_cookie(response)
        _apply_security_headers(request, response)
        return response

    set_current_owner_id(user["id"] if user else None)
    try:
        response = await call_next(request)
    finally:
        set_current_owner_id(None)
    _apply_security_headers(request, response)
    return response


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(NotAuthenticatedError)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedError):
    return JSONResponse({"detail": "Authentication required."}, status_code=401)


def _current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


@app.get("/api/health")
def health():
    from app.config import config_warnings, load_config

    try:
        config = load_config(strict=False)
        return {
            "status": "ok",
            "environment": config.environment,
            "database": "postgres" if config.is_postgres else "sqlite",
            "auth_mode": config.auth_mode,
            "warnings": config_warnings(config),
        }
    except Exception as exc:
        logger.exception("Health config check failed")
        return {"status": "degraded", "error": str(exc)}


def _start_fresh_session(request: Request, response: Response, user: dict) -> None:
    # Always issue a new token on sign-in (prevents session fixation).
    end_session(request.cookies.get(SESSION_COOKIE))
    token = start_session(
        user["id"],
        auth_method="password",
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookie(response, token)


@app.post(
    "/api/auth/register",
    response_model=AuthUser,
    status_code=status.HTTP_201_CREATED,
)
def auth_register(payload: RegisterRequest, request: Request, response: Response):
    user = register_user(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        confirm_adult=payload.confirm_adult,
        accept_terms=payload.accept_terms,
    )
    if payload.ai_processing is not None:
        # Decision Q: new users choose at sign-up; unticked means off.
        from app.database import update_settings

        update_settings(user["id"], ai_processing=payload.ai_processing)
    _start_fresh_session(request, response, user)
    return user


@app.post("/api/auth/account/delete")
def auth_delete_account(payload: AccountDeleteRequest, request: Request, response: Response):
    """Delete your account and everything in it (change 025). Your password
    and the word DELETE are the checks; it can't be undone."""
    from app.auth import delete_account

    user = _current_user(request)
    if payload.confirm.strip() != "DELETE":
        raise HTTPException(status_code=422, detail="Type DELETE to confirm.")
    counts = delete_account(user["id"], password=payload.password)
    clear_session_cookie(response)
    return {"status": "deleted", "removed": counts}


@app.get("/api/onboarding")
def read_onboarding():
    """Whether to show the setup questions (change 024), and their choices."""
    from app.database import onboarding_state

    return onboarding_state()


@app.post("/api/onboarding")
def answer_onboarding(payload: OnboardingAnswers):
    from app.database import save_onboarding

    return save_onboarding(payload.model_dump())


@app.post("/api/onboarding/skip")
def skip_onboarding():
    from app.database import update_settings

    update_settings(onboarding_done=True)
    return {"status": "skipped"}


@app.post("/api/auth/login", response_model=AuthUser)
def auth_login(payload: LoginRequest, request: Request, response: Response):
    user = authenticate_password(payload.email, payload.password)
    _start_fresh_session(request, response, user)
    return user


@app.get("/api/auth/providers")
def auth_providers():
    from app.config import load_config

    return {"google": load_config(strict=False).google_enabled}


def _login_redirect(error: str, intent: str = "signin") -> RedirectResponse:
    tab = "&tab=register" if intent == "register" else ""
    response = RedirectResponse(f"/login?error={error}{tab}", status_code=302)
    response.delete_cookie(google_auth.STATE_COOKIE, path="/")
    return response


@app.get("/api/auth/google/start")
def google_start(
    intent: str = Query("signin", pattern="^(signin|register)$"),
    adult: bool = Query(False),
    terms: bool = Query(False),
):
    from app.auth import _secure_cookies
    from app.config import load_config

    config = load_config(strict=False)
    if not config.google_enabled:
        raise HTTPException(status_code=404, detail="Google sign-in is not configured.")
    if intent == "register" and not (adult and terms):
        return _login_redirect("google_consent", intent)
    cookie, url = google_auth.begin(
        config, intent=intent, adult=adult, terms=terms
    )
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        key=google_auth.STATE_COOKIE,
        value=cookie,
        max_age=google_auth.STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
        path="/",
    )
    return response


@app.get("/auth/google/callback")
def google_callback(
    request: Request,
    code: Optional[str] = Query(None, max_length=2048),
    state: Optional[str] = Query(None, max_length=512),
    error: Optional[str] = Query(None, max_length=200),
):
    import hmac

    from app.config import load_config

    config = load_config(strict=False)
    if not config.google_enabled:
        raise HTTPException(status_code=404, detail="Google sign-in is not configured.")

    flow = google_auth.unpack_state(request.cookies.get(google_auth.STATE_COOKIE))
    intent = flow.get("intent", "signin") if flow else "signin"
    if error:
        return _login_redirect("google_denied", intent)
    if (
        flow is None
        or not code
        or not state
        or not hmac.compare_digest(str(flow.get("state", "")), state)
    ):
        return _login_redirect("google_state", intent)

    try:
        identity = google_auth.exchange_code(
            config,
            code=code,
            verifier=str(flow.get("verifier", "")),
            nonce=str(flow.get("nonce", "")),
        )
        user, outcome = sign_in_with_google(
            sub=identity["sub"],
            email=identity["email"],
            display_name=identity["name"],
            intent=intent,
            adult=bool(flow.get("adult")),
            terms=bool(flow.get("terms")),
        )
    except (google_auth.GoogleAuthError, GoogleSignInError) as exc:
        return _login_redirect(exc.code, intent)

    response = RedirectResponse(
        "/?google=linked" if outcome == "linked" else "/", status_code=302
    )
    response.delete_cookie(google_auth.STATE_COOKIE, path="/")
    _start_fresh_session(request, response, user)
    return response


@app.get("/api/auth/me", response_model=AuthUser)
def auth_me(request: Request):
    return _current_user(request)


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    end_session(request.cookies.get(SESSION_COOKIE))
    clear_session_cookie(response)
    return {"status": "logged_out"}


@app.post("/api/auth/logout-all")
def auth_logout_all(request: Request, response: Response):
    user = _current_user(request)
    revoked = end_all_sessions(user["id"])
    clear_session_cookie(response)
    return {"status": "logged_out", "sessions_revoked": revoked}


@app.post(
    "/api/auth/password/forgot",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def auth_forgot_password(payload: ForgotPasswordRequest):
    return request_password_reset(payload.email)


@app.post("/api/auth/password/reset", response_model=AuthUser)
def auth_reset_password(
    payload: ResetPasswordRequest, request: Request, response: Response
):
    user = reset_password_with_code(
        payload.email, payload.code, payload.new_password
    )
    _start_fresh_session(request, response, user)
    return user


@app.post("/api/auth/password/change")
def auth_change_password(payload: PasswordChangeRequest, request: Request):
    user = _current_user(request)
    revoked = change_password(
        user["id"],
        current_password=payload.current_password,
        new_password=payload.new_password,
        keep_token=request.cookies.get(SESSION_COOKIE),
    )
    return {"status": "password_changed", "other_sessions_revoked": revoked}


def _process_url_item(item_id: int) -> dict:
    mark_item_processing(item_id)
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    try:
        fetched = fetch_url(item["source_url"])
        final_url = fetched.get("final_url") or item["source_url"]
        # The link card (change 015): oEmbed for videos (the exact title and
        # channel), the page's structured data, tags and main text. No AI.
        oembed = fetch_oembed(final_url) if video_site(final_url) else None
        page = read_page(fetched["html"]) if fetched.get("html") else None
        card = build_card(tidy_url(final_url), page, oembed,
                          fallback_title=fetched.get("title"), fallback_text=fetched.get("raw_text"))
        processed = complete_url_item_processing(
            item_id,
            title=card["title"] if oembed and oembed.get("title") else fetched["title"],
            raw_text=fetched["raw_text"],
            mime_type=fetched.get("mime_type"),
            final_url=fetched.get("final_url"),
            link_card=card,
        )
        if processed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return processed
    except ValueError as exc:
        failed = fail_item_processing(item_id, str(exc))
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed
    except Exception as exc:
        logger.exception("URL processing failed")
        failed = fail_item_processing(
            item_id,
            "Unable to fetch or extract this URL.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed


def _process_pdf_item(item_id: int) -> dict:
    mark_item_processing(item_id)
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    storage_path = item.get("storage_path")
    if not storage_path:
        failed = fail_item_processing(
            item_id,
            "Stored PDF file is missing.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    try:
        data = read_stored_bytes(storage_path)
        extracted = extract_pdf_text(
            data,
            original_filename=item.get("original_filename"),
        )
        # Decision P: a long PDF gets one AI summary, once, when it's read.
        from app.capture.pdf_extract import is_long, summarize_pdf

        summary = summarize_pdf(extracted) if is_long(extracted) and _ai_allowed_for_you() else None
        processed = complete_pdf_item_processing(
            item_id,
            title=extracted["title"],
            raw_text=extracted["raw_text"],
            extracted_text=extracted["extracted_text"],
            mime_type=extracted.get("mime_type"),
            source_summary=summary,
        )
        if processed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return processed
    except FileNotFoundError:
        failed = fail_item_processing(
            item_id,
            "Stored PDF file is missing.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    except ValueError as exc:
        failed = fail_item_processing(item_id, str(exc))
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed
    except Exception as exc:
        logger.exception("PDF processing failed")
        failed = fail_item_processing(
            item_id,
            "Unable to extract text from this PDF.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed


def _ai_allowed_for_you() -> bool:
    """AI is set up, and your AI switch (change 025) is on."""
    from app import llm
    from app.database import get_settings

    try:
        return llm.is_configured() and bool(get_settings().get("ai_processing", True))
    except Exception:
        return False


def _process_image_item(item_id: int) -> dict:
    mark_item_processing(item_id)
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    storage_path = item.get("storage_path")
    if not storage_path:
        failed = fail_item_processing(item_id, "Stored image file is missing.")
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    try:
        data = read_stored_bytes(storage_path)
        processed_payload = process_image_bytes(
            data,
            original_filename=item.get("original_filename") or "image.png",
            mime_type=item.get("mime_type") or "image/png",
            # Change 021 (decision O): a vision call only for an image with no
            # readable text and no note of yours, and only if AI is allowed.
            user_context=item.get("user_context"),
            allow_vision=_ai_allowed_for_you(),
        )
        store_thumbnail_bytes(storage_path, processed_payload["thumbnail_bytes"])
        processed = complete_image_item_processing(
            item_id,
            title=processed_payload["title"],
            raw_text=processed_payload["raw_text"],
            extracted_text=processed_payload["extracted_text"],
            ai_description=processed_payload["ai_description"],
            mime_type=processed_payload.get("mime_type"),
        )
        if processed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return processed
    except FileNotFoundError:
        failed = fail_item_processing(item_id, "Stored image file is missing.")
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    except ValueError as exc:
        failed = fail_item_processing(item_id, str(exc))
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed
    except Exception as exc:
        logger.exception("Image processing failed")
        failed = fail_item_processing(
            item_id,
            "Unable to process this image.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed


def _process_voice_item(
    item_id: int, candidate_transcript: Optional[str] = None
) -> dict:
    mark_item_processing(item_id)
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    storage_path = item.get("storage_path")
    if not storage_path:
        failed = fail_item_processing(item_id, "Stored audio file is missing.")
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    try:
        data = read_stored_bytes(storage_path)
        processed_payload = process_voice_bytes(
            data,
            original_filename=item.get("original_filename") or "voice-note.webm",
            mime_type=item.get("mime_type") or "audio/webm",
            candidate_transcript=candidate_transcript,
        )
        processed = complete_voice_item_processing(
            item_id,
            title=processed_payload["title"],
            raw_text=processed_payload["raw_text"],
            extracted_text=processed_payload["extracted_text"],
            mime_type=processed_payload.get("mime_type"),
        )
        if processed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return processed
    except FileNotFoundError:
        failed = fail_item_processing(item_id, "Stored audio file is missing.")
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    except ValueError as exc:
        failed = fail_item_processing(item_id, str(exc))
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed
    except Exception as exc:
        logger.exception("Voice processing failed")
        failed = fail_item_processing(
            item_id,
            "Unable to process this voice note.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed


@app.post("/api/items", response_model=InboxItem)
def create_item(payload: InboxItemCreate):
    try:
        return add_item_to_db(payload.raw_text)
    except Exception as exc:
        logger.exception("Failed to save inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save item. Please try again.",
        ) from exc


def _clean_context(value: Optional[str]) -> Optional[str]:
    """The user's note that came with a source: trimmed, None if blank."""
    cleaned = (value or "").strip()
    if len(cleaned) > NOTE_MAX_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Your note can be up to {NOTE_MAX_LENGTH} characters.",
        )
    return cleaned or None


@app.post("/api/items/url", response_model=InboxItem)
def create_url_item(payload: UrlItemCreate):
    try:
        # Tracking parts (utm_*, si=...) go before anything is saved (change 015).
        url = tidy_url(validate_public_http_url(payload.url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    context = _clean_context(payload.context)
    try:
        item = add_url_item_to_db(url, user_context=context)
    except Exception as exc:
        logger.exception("Failed to save URL item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save URL. Please try again.",
        ) from exc

    # A link you saved before reuses what was read: no fetch, and with no new
    # note of yours, no AI call either (it's filed like the earlier one).
    from app.database import find_saved_link, reuse_saved_link

    earlier = find_saved_link(url, exclude_item_id=item["id"])
    if earlier is not None:
        same_note = not context or context == (earlier.get("user_context") or None)
        reused = reuse_saved_link(item["id"], earlier["id"], copy_filing=same_note)
        if reused is not None:
            return reused
    return _process_url_item(item["id"])


@app.post("/api/items/pdf", response_model=InboxItem)
async def create_pdf_item(
    file: UploadFile = File(...),
    context: Optional[str] = Form(None),
):
    user_context = _clean_context(context)
    data = await file.read()
    try:
        safe_filename = validate_pdf_upload(
            file.filename or "document.pdf",
            file.content_type,
            data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        storage_path = store_pdf_bytes(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to store PDF upload")
        raise HTTPException(
            status_code=500,
            detail="Unable to store PDF. Please try again.",
        ) from exc

    mime_type = (file.content_type or "application/pdf").split(";", 1)[0].strip()
    try:
        item = add_pdf_item_to_db(
            safe_filename, storage_path, mime_type, user_context=user_context
        )
    except Exception as exc:
        logger.exception("Failed to save PDF item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save PDF. Please try again.",
        ) from exc

    return _process_pdf_item(item["id"])


@app.post("/api/items/image", response_model=InboxItem)
async def create_image_item(
    file: UploadFile = File(...),
    context: Optional[str] = Form(None),
):
    user_context = _clean_context(context)
    data = await file.read()
    try:
        safe_filename, detected_mime, extension = validate_image_upload(
            file.filename or "image.png",
            file.content_type,
            data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        storage_path = store_image_bytes(data, extension)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to store image upload")
        raise HTTPException(
            status_code=500,
            detail="Unable to store image. Please try again.",
        ) from exc

    mime_type = detected_mime
    if file.content_type:
        declared = file.content_type.split(";", 1)[0].strip().lower()
        if declared in {
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp",
            "image/gif",
        }:
            mime_type = declared
    try:
        item = add_image_item_to_db(
            safe_filename, storage_path, mime_type, user_context=user_context
        )
    except Exception as exc:
        logger.exception("Failed to save image item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save image. Please try again.",
        ) from exc

    return _process_image_item(item["id"])


@app.post("/api/items/voice", response_model=InboxItem)
async def create_voice_item(
    file: UploadFile = File(...),
    transcript: Optional[str] = Form(None),
    context: Optional[str] = Form(None),
):
    user_context = _clean_context(context)
    data = await file.read()
    try:
        safe_filename, detected_mime, extension = validate_audio_upload(
            file.filename or "voice-note.webm",
            file.content_type,
            data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        storage_path = store_audio_bytes(data, extension)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to store voice upload")
        raise HTTPException(
            status_code=500,
            detail="Unable to store voice note. Please try again.",
        ) from exc

    mime_type = detected_mime
    if file.content_type:
        declared = file.content_type.split(";", 1)[0].strip().lower()
        if declared in {
            "audio/webm",
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
            "audio/mpeg",
            "audio/mp3",
            "audio/mp4",
            "audio/m4a",
            "audio/x-m4a",
            "audio/ogg",
            "video/webm",
        }:
            mime_type = declared if declared != "video/webm" else "audio/webm"
    try:
        item = add_voice_item_to_db(
            safe_filename, storage_path, mime_type, user_context=user_context
        )
    except Exception as exc:
        logger.exception("Failed to save voice item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save voice note. Please try again.",
        ) from exc

    return _process_voice_item(item["id"], candidate_transcript=transcript)


@app.get("/api/items/{item_id}/file")
def get_item_source_file(
    item_id: int,
    variant: Optional[str] = Query(None, max_length=20),
):
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item["item_type"] not in {"pdf", "image", "voice"} or not item.get(
        "storage_path"
    ):
        raise HTTPException(
            status_code=404,
            detail="No stored file for this item.",
        )
    relative = item["storage_path"]
    media_type = item.get("mime_type") or "application/octet-stream"
    filename = item.get("original_filename") or "download"
    if variant == "thumb" and item["item_type"] == "image":
        relative = thumbnail_relative_path(item["storage_path"])
        media_type = "image/jpeg"
        filename = f"thumb_{Path(filename).stem}.jpg"
    try:
        path = resolve_storage_path(relative)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Stored file not found.") from exc
    if item["item_type"] == "pdf" and not media_type:
        media_type = "application/pdf"
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
    )


@app.patch("/api/items/{item_id}/extracted-text", response_model=InboxItem)
def patch_extracted_text(item_id: int, payload: ExtractedTextUpdate):
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item["item_type"] not in {"image", "voice", "pdf"}:
        raise HTTPException(
            status_code=400,
            detail="Extracted text can only be edited for image, voice, or PDF items.",
        )
    updated = update_item_extracted_text(item_id, payload.extracted_text)
    if updated is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return updated


@app.post("/api/items/{item_id}/retry", response_model=InboxItem)
def retry_item_processing(item_id: int):
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item["item_type"] not in {"url", "pdf", "image", "voice"}:
        raise HTTPException(
            status_code=400,
            detail="Only capture items (URL/PDF/image/voice) can be retried here.",
        )
    if item["processing_status"] == "ready":
        return item
    if item["processing_status"] == "processing":
        raise HTTPException(
            status_code=409,
            detail="This item is already being processed.",
        )
    if not claim_item_for_retry(item_id):
        current = get_item_from_db(item_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        if current["processing_status"] == "ready":
            return current
        raise HTTPException(
            status_code=409,
            detail="This item is already being processed or could not be retried.",
        )
    if item["item_type"] == "url":
        return _process_url_item(item_id)
    if item["item_type"] == "pdf":
        return _process_pdf_item(item_id)
    if item["item_type"] == "image":
        return _process_image_item(item_id)
    return _process_voice_item(item_id)


@app.get("/api/items", response_model=List[InboxItem])
def get_items(
    search: Optional[str] = Query(None, alias="q", max_length=200),
    item_type: Optional[str] = Query(None, max_length=100),
    category: Optional[str] = Query(None, max_length=100),
    priority: Optional[Priority] = Query(None),
    processing_status: Optional[str] = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    bot: Optional[str] = Query(None, max_length=20),
    order: Literal["asc", "desc"] = Query("asc"),
    topic_id: Optional[int] = Query(None, ge=1),
):
    bot = _life_area(bot)
    if topic_id is not None and not owns_topic(topic_id):
        raise HTTPException(status_code=404, detail="Topic not found.")
    try:
        return list_items_from_db(
            search=search,
            item_type=item_type,
            category=category,
            priority=priority,
            processing_status=processing_status,
            limit=limit,
            offset=offset,
            bot=bot,
            newest_first=order == "desc",
            topic_id=topic_id,
        )
    except Exception as exc:
        logger.exception("Failed to load inbox items")
        raise HTTPException(
            status_code=500,
            detail="Unable to load items. Please try again.",
        ) from exc


def _markdown_code_block(value: str) -> str:
    fence = "```"
    while fence in value:
        fence += "`"
    return f"{fence}text\n{value}\n{fence}"


@app.get("/api/items/export.md", response_class=Response)
def export_items_markdown():
    try:
        items = list_items_from_db(limit=None, offset=0)
    except Exception as exc:
        logger.exception("Failed to export inbox items")
        raise HTTPException(
            status_code=500,
            detail="Unable to export items. Please try again.",
        ) from exc

    markdown = ["# Life Inbox Export", ""]
    for item in items:
        markdown.extend([f"## Note {item['id']}", ""])
        metadata = (
            ("Title", "title"),
            ("Type", "item_type"),
            ("Created", "created_at"),
            ("Source URL", "source_url"),
            ("Original filename", "original_filename"),
        )
        for label, key in metadata:
            value = item.get(key)
            if value is not None and str(value).strip():
                one_line_value = str(value).replace("\r", " ").replace("\n", " ")
                markdown.append(f"- **{label}:** {one_line_value}")

        included_text = set()
        for label, key in (
            ("Your note", "user_context"),
            ("Text", "raw_text"),
            ("Extracted text", "extracted_text"),
            ("AI description", "ai_description"),
        ):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip() or value in included_text:
                continue
            included_text.add(value)
            markdown.extend(["", f"### {label}", "", _markdown_code_block(value)])
        updates = list_item_updates(item["id"]) or []
        if updates:
            markdown.extend(["", "### Updates", ""])
            for update in reversed(updates):  # oldest first, like a diary
                markdown.append(f"- {update['created_at'][:10]}: {update['text']} ({update['task_text']})")
        markdown.extend(["", "---", ""])

    from app.database import list_memory

    facts = list_memory(statuses=("suggested", "confirmed", "expired"))
    if facts:
        markdown.extend(["## What Life Inbox learned about you", ""])
        for fact in facts:
            where = f" (from note {', '.join('#' + str(i) for i in fact['source_item_ids'])})" if fact["source_item_ids"] else ""
            markdown.append(f"- {fact['text']} · {fact['status']}{where}")
        markdown.append("")

    return Response(
        content="\n".join(markdown).rstrip() + "\n",
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="life-inbox-export.md"'},
    )


@app.get("/api/items/{item_id}", response_model=InboxItem)
def read_item(item_id: int):
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return item


@app.patch("/api/items/{item_id}/context", response_model=ItemContextResult)
def change_item_context(item_id: int, payload: ItemContextUpdate):
    """Edit your note on a saved source (change 023), then file it again from
    your words (one call, as saving does). Filing failing never loses the edit."""
    from app.database import update_item_context

    item = update_item_context(item_id, payload.context)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    refiled = False
    if get_note_from_db(item_id):
        try:
            filing.file_items([item_id])
            refiled = True
        except Exception:
            logger.exception("Re-filing after a note edit failed")
    return {"item": get_item_from_db(item_id) or item, "refiled": refiled}


@app.put("/api/items/{item_id}", response_model=InboxItem)
def update_item(item_id: int, payload: InboxItemUpdate):
    try:
        item = update_item_in_db(item_id, payload.raw_text)
    except Exception as exc:
        logger.exception("Failed to update inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to update item. Please try again.",
        ) from exc

    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return item


@app.delete(
    "/api/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_item(item_id: int):
    try:
        deleted = delete_item_from_db(item_id)
    except Exception as exc:
        logger.exception("Failed to delete inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to delete item. Please try again.",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/items/{item_id}/complete", response_model=InboxItem)
def complete_item(item_id: int):
    try:
        item = complete_item_in_db(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to complete inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to complete item. Please try again.",
        ) from exc
    return item


@app.post("/api/notes", response_model=Note, deprecated=True)
def create_note(payload: NoteCreate):
    try:
        return add_note_to_db(payload.text)
    except Exception as exc:
        logger.exception("Failed to save note")
        raise HTTPException(
            status_code=500,
            detail="Unable to save note. Please try again.",
        ) from exc


@app.get("/api/notes", response_model=List[Note], deprecated=True)
def get_notes():
    try:
        return list_notes_from_db()
    except Exception as exc:
        logger.exception("Failed to load notes")
        raise HTTPException(
            status_code=500,
            detail="Unable to load notes. Please try again.",
        ) from exc


@app.put("/api/notes/{note_id}", response_model=Note, deprecated=True)
def update_note(note_id: int, payload: NoteUpdate):
    try:
        note = update_note_in_db(note_id, payload.text)
    except Exception as exc:
        logger.exception("Failed to update note")
        raise HTTPException(
            status_code=500,
            detail="Unable to update note. Please try again.",
        ) from exc

    if note is None:
        raise HTTPException(status_code=404, detail="Note not found.")
    return note


@app.delete(
    "/api/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    deprecated=True,
)
def delete_note(note_id: int):
    try:
        deleted = delete_note_from_db(note_id)
    except Exception as exc:
        logger.exception("Failed to delete note")
        raise HTTPException(
            status_code=500,
            detail="Unable to delete note. Please try again.",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/tasks", response_model=List[Task])
def get_tasks(
    task_status: TaskListStatus = Query("open", alias="status"),
    bot: Optional[str] = Query(None, max_length=20),
):
    bot = _life_area(bot)
    try:
        return list_tasks_from_db(task_status, bot=bot)
    except Exception as exc:
        logger.exception("Failed to load tasks")
        raise HTTPException(
            status_code=500,
            detail="Unable to load tasks. Please try again.",
        ) from exc

@app.post("/api/tasks", response_model=Task, status_code=201)
def create_task(payload: TaskCreate):
    text = payload.text.strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="Task title cannot be empty.",
        )

    try:
        return create_manual_task(
            text=text,
            priority=payload.priority,
            due_on=payload.due_on.isoformat() if payload.due_on else None,
        )
    except Exception as exc:
        logger.exception("Failed to create manual task")
        raise HTTPException(
            status_code=500,
            detail="Unable to create task. Please try again.",
        ) from exc




def _transition_task(task_id: int, task_status: str):
    try:
        task = set_task_status(task_id, task_status)
    except Exception as exc:
        logger.exception("Failed to update task status")
        raise HTTPException(
            status_code=500,
            detail="Unable to update task. Please try again.",
        ) from exc

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks/{task_id}/date", response_model=Task)
def change_task_date(task_id: int, payload: TaskDateUpdate):
    """Set, postpone or move a task's date as yours; recorded on its note."""
    try:
        task = set_task_date(task_id, payload.due_on.isoformat(), payload.due_time)
    except Exception as exc:
        logger.exception("Failed to change task date")
        raise HTTPException(
            status_code=500,
            detail="Unable to change the date. Please try again.",
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.get("/api/items/{item_id}/updates", response_model=List[TaskDateChange])
def item_updates(item_id: int):
    """The date history of the note's tasks, newest first."""
    updates = list_item_updates(item_id)
    if updates is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return updates


@app.patch("/api/tasks/{task_id}", response_model=Task)
def update_task(task_id: int, payload: TaskUpdate):
    """Edit a task: its text, your priority (null goes back to the AI's; a
    Priority view drag), or its date (set, or cleared)."""
    fields = payload.model_fields_set
    try:
        if fields == {"priority"}:
            task = set_task_priority(task_id, payload.priority)
        else:
            task = update_task_in_db(
                task_id,
                text=payload.text,
                priority=payload.priority,
                due_on=payload.due_on.isoformat() if payload.due_on else None,
                clear_due=payload.clear_due_date,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to update task priority")
        raise HTTPException(
            status_code=500,
            detail="Unable to update the task. Please try again.",
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks/{task_id}/complete", response_model=Task)
def complete_task(task_id: int):
    return _transition_task(task_id, "completed")


@app.post("/api/tasks/{task_id}/reopen", response_model=Task)
def reopen_task(task_id: int):
    return _transition_task(task_id, "open")


@app.post("/api/tasks/{task_id}/dismiss", response_model=Task)
def dismiss_task(task_id: int):
    return _transition_task(task_id, "dismissed")


@app.post("/api/tasks/{task_id}/confirm-timing", response_model=Task)
def confirm_timing(task_id: int, payload: TaskTimingConfirm):
    try:
        task = confirm_task_timing(task_id, payload.timing_text)
    except Exception as exc:
        logger.exception("Failed to confirm task timing")
        raise HTTPException(
            status_code=500,
            detail="Unable to confirm task timing. Please try again.",
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks/{task_id}/snooze", response_model=Task)
def snooze_task(task_id: int, payload: TaskSnoozeRequest):
    try:
        task = snooze_task_in_db(task_id, payload.until.strip())
    except Exception as exc:
        logger.exception("Failed to snooze task")
        raise HTTPException(
            status_code=500,
            detail="Unable to snooze task. Please try again.",
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks/{task_id}/reminder", response_model=Task)
def set_task_reminder(task_id: int, payload: TaskReminderRequest):
    try:
        task = set_task_reminder_in_db(task_id, payload.reminder_at.strip())
    except Exception as exc:
        logger.exception("Failed to set reminder")
        raise HTTPException(
            status_code=500,
            detail="Unable to set reminder. Please try again.",
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.get("/api/notifications/settings")
def notification_settings():
    from app.notifications.service import vapid_is_configured, vapid_public_key

    try:
        return {
            **get_notification_settings(),
            "push_available": vapid_is_configured(),
            "vapid_public_key": vapid_public_key(),
        }
    except Exception as exc:
        logger.exception("Failed to load notification settings")
        raise HTTPException(
            status_code=500,
            detail="Unable to load notification settings. Please try again.",
        ) from exc


@app.put("/api/notifications/settings")
def update_notification_settings(payload: NotificationPreferencesUpdate):
    from app.notifications.service import vapid_is_configured

    if payload.enabled and not vapid_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Browser notifications are not configured on this server.",
        )
    try:
        return save_notification_settings(
            enabled=payload.enabled,
            daily_digest_time=payload.daily_digest_time,
            timezone_name=payload.timezone,
            include_unscheduled_prompt=payload.include_unscheduled_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to update notification settings")
        raise HTTPException(
            status_code=500,
            detail="Unable to save notification settings. Please try again.",
        ) from exc


@app.post("/api/notifications/subscriptions", status_code=201)
def create_notification_subscription(payload: PushSubscriptionRequest):
    from app.notifications.service import (
        validate_push_endpoint,
        vapid_is_configured,
    )

    if not vapid_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Browser notifications are not configured on this server.",
        )
    try:
        endpoint = validate_push_endpoint(payload.endpoint)
        save_push_subscription(
            endpoint=endpoint,
            p256dh=payload.keys["p256dh"],
            auth=payload.keys["auth"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to save push subscription")
        raise HTTPException(
            status_code=500,
            detail="Unable to enable browser notifications. Please try again.",
        ) from exc
    return {"registered": True}


@app.delete("/api/notifications/subscriptions")
def delete_notification_subscription(payload: PushSubscriptionRequest):
    from app.notifications.service import validate_push_endpoint

    try:
        endpoint = validate_push_endpoint(payload.endpoint)
        removed = remove_push_subscription(endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to remove push subscription")
        raise HTTPException(
            status_code=500,
            detail="Unable to remove browser subscription. Please try again.",
        ) from exc
    return {"removed": removed}


@app.get("/api/attention")
def attention_board():
    try:
        return get_attention_board()
    except Exception as exc:
        logger.exception("Failed to load attention board")
        raise HTTPException(
            status_code=500,
            detail="Unable to load attention board. Please try again.",
        ) from exc


@app.get("/api/dashboard/glance", response_model=Glance)
def dashboard_glance(
    bot: Optional[str] = Query(None, max_length=20),
    tz: Optional[str] = Query(None, max_length=64),
):
    """The Dashboard's numbers and notes, worked out by code; follows the lens.
    `tz` is the browser's time zone, so "today" and "this week" are the user's
    own; without it, the server's configured zone."""
    from datetime import datetime as _datetime
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from app.attention.dates import configured_timezone
    from app.attention.glance import build_glance

    bot = _life_area(bot)
    zone = configured_timezone()
    if tz:
        try:
            zone = ZoneInfo(tz.strip())
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Unknown time zone.") from exc
    try:
        return build_glance(
            **glance_rows(),
            bots=[{"key": entry.key, "name": entry.name} for entry in BOTS],
            today=_datetime.now(zone).date(),
            zone=zone,
            lens=bot,
        )
    except Exception as exc:
        logger.exception("Failed to build the dashboard")
        raise HTTPException(
            status_code=500,
            detail="Unable to load the dashboard. Please try again.",
        ) from exc


@app.get("/api/briefing")
def daily_briefing():
    try:
        return get_daily_briefing()
    except Exception as exc:
        logger.exception("Failed to load daily briefing")
        raise HTTPException(
            status_code=500,
            detail="Unable to load daily briefing. Please try again.",
        ) from exc


@app.get("/api/calendar/events", response_model=List[CalendarEvent])
def get_calendar_events(
    start: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end: str = Query(..., description="End date in YYYY-MM-DD format"),
    bot: Optional[str] = Query(None, max_length=20),
):
    from datetime import date as date_cls

    bot = _life_area(bot)

    try:
        start_d = date_cls.fromisoformat(start.strip())
        end_d = date_cls.fromisoformat(end.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Dates must be formatted as YYYY-MM-DD.",
        ) from exc

    if start_d > end_d:
        raise HTTPException(
            status_code=400,
            detail="Start date must not be after end date.",
        )

    try:
        return list_calendar_events_from_db(start_d.isoformat(), end_d.isoformat(), bot=bot)
    except Exception as exc:
        logger.exception("Failed to load calendar events")
        raise HTTPException(
            status_code=500,
            detail="Unable to load calendar events. Please try again.",
        ) from exc


@app.get("/api/calendar/status")
def calendar_status():
    adapter = get_calendar_adapter()
    status = adapter.status()
    return {
        "provider": status.provider,
        "configured": status.configured,
        "oauth_connected": status.oauth_connected,
        "writes_enabled": status.writes_enabled,
        "mode": status.mode,
        "message": status.message,
    }


@app.post("/api/calendar/preview")
def calendar_preview(payload: CalendarPreviewRequest):
    from datetime import date as date_cls

    from app.attention.dates import configured_timezone, parse_timing_phrase

    task = None
    for candidate in list_tasks_from_db(status_filter="all"):
        if candidate["id"] == payload.task_id:
            task = candidate
            break
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    title = (payload.title or task["text"]).strip()
    if payload.start_date:
        try:
            start = date_cls.fromisoformat(payload.start_date.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="start_date must be YYYY-MM-DD.",
            ) from exc
    elif task.get("due_on"):
        start = date_cls.fromisoformat(task["due_on"])
    else:
        parsed = parse_timing_phrase(task.get("timing_text"))
        if parsed.due_date is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Task has no normalized date. Confirm timing before "
                    "previewing a calendar event."
                ),
            )
        start = parsed.due_date

    if not task.get("timing_confirmed"):
        parsed = parse_timing_phrase(task.get("timing_text"))
        if parsed.needs_confirmation:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Confirm the task date before creating a calendar preview. "
                    "Ambiguous timing requires explicit confirmation."
                ),
            )

    adapter = get_calendar_adapter()
    draft = adapter.preview_event(
        task_id=task["id"],
        title=title,
        start_date=start,
        description=payload.description or "",
        timezone_name=str(configured_timezone()),
    )
    store_draft(draft, owner_user_id=require_owner_id())
    return {
        "draft_id": draft.draft_id,
        "task_id": draft.task_id,
        "title": draft.title,
        "start_date": draft.start_date,
        "end_date": draft.end_date,
        "description": draft.description,
        "timezone": draft.timezone_name,
        "provider": draft.provider,
        "status": draft.status,
        "confirmation_required": draft.confirmation_required,
        "notes": draft.notes,
    }


@app.post("/api/calendar/confirm")
def calendar_confirm(payload: CalendarConfirmRequest):
    owner_id = require_owner_id()
    draft = get_draft(payload.draft_id, owner_user_id=owner_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail="Calendar draft not found. Create a preview first.",
        )
    adapter = get_calendar_adapter()
    try:
        confirmed = adapter.confirm_event(draft)
    except CalendarWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Calendar confirm failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to confirm calendar action.",
        ) from exc

    store_draft(confirmed, owner_user_id=owner_id)
    receipt = save_calendar_receipt(
        draft_id=confirmed.draft_id,
        task_id=confirmed.task_id,
        provider=confirmed.provider,
        status=confirmed.status,
        payload={
            "title": confirmed.title,
            "start_date": confirmed.start_date,
            "end_date": confirmed.end_date,
            "timezone": confirmed.timezone_name,
            "notes": confirmed.notes,
        },
    )
    return {
        "draft_id": confirmed.draft_id,
        "task_id": confirmed.task_id,
        "status": confirmed.status,
        "provider": confirmed.provider,
        "notes": confirmed.notes,
        "receipt": receipt,
    }


def _life_area(bot: Optional[str]) -> Optional[str]:
    """Validate a `?bot=` lens: one of the five life areas, or none."""
    if bot is None or not bot.strip():
        return None
    key = bot.strip().lower()
    if key not in BOT_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown life area. Use one of: {', '.join(BOT_KEYS)}.",
        )
    return key


@app.get("/api/bots", response_model=List[LifeBot])
def get_life_bots():
    """The five life areas, with counts and a one-line status each."""
    try:
        return list_bots_from_db()
    except Exception as exc:
        logger.exception("Failed to load life areas")
        raise HTTPException(
            status_code=500,
            detail="Unable to load life areas. Please try again.",
        ) from exc


@app.get("/api/topics", response_model=List[Topic])
def get_topics(
    include_archived: bool = Query(False),
    bot: Optional[str] = Query(None, max_length=20),
):
    bot = _life_area(bot)
    try:
        return list_topics_from_db(include_archived=include_archived, bot=bot)
    except Exception as exc:
        logger.exception("Failed to load topics")
        raise HTTPException(
            status_code=500,
            detail="Unable to load topics. Please try again.",
        ) from exc


@app.get("/api/topics/{topic_id}", response_model=TopicDetail)
def get_topic(topic_id: int):
    try:
        topic = get_topic_detail(topic_id)
    except Exception as exc:
        logger.exception("Failed to load topic")
        raise HTTPException(
            status_code=500,
            detail="Unable to load the topic. Please try again.",
        ) from exc
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return topic


@app.post("/api/topics/suggest-parent", response_model=TopicParentSuggestion)
def suggest_topic_parent(payload: TopicParentSuggestionRequest):
    """Step 1 of adding a topic: ask whether it should be a subtopic.

    Nothing is saved here; the user decides, then calls POST /api/topics.
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Topic name is required.")
    if topic_name_exists(name):
        raise HTTPException(status_code=409, detail="A topic with that name already exists.")
    try:
        return suggest_parent_topic(
            name,
            (payload.description or "").strip() or None,
            list_topics_from_db(),
        )
    except Exception:
        logger.exception("Topic parent suggestion failed")
        return {"suggested_parent": None, "reason": None, "mode": "none"}


@app.post("/api/topics", response_model=Topic)
def create_topic(payload: TopicCreate):
    bot_key = _life_area(payload.bot_key)
    try:
        return create_topic_in_db(
            payload.name.strip(),
            (payload.description or "").strip() or None,
            parent_topic_id=payload.parent_topic_id,
            bot_key=bot_key,
        )
    except TopicConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to create topic")
        raise HTTPException(
            status_code=500,
            detail="Unable to create topic. Please try again.",
        ) from exc


@app.delete("/api/topics/{topic_id}", response_model=TopicDeleteResult)
def delete_topic(topic_id: int):
    """Delete a user-created topic; built-in topics can't be deleted.

    A subtopic's notes move to its parent. A main topic's notes are re-sorted
    into the user's remaining topics (never into a newly invented one).
    """
    try:
        plan = get_topic_deletion_plan(topic_id)
    except TopicConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Topic not found.")

    assignments = {}
    mode = "parent" if plan["parent"] else "none"
    if plan["parent"] is None and plan["notes"]:
        remaining = []
        for topic in list_topics_from_db():
            if topic["id"] == topic_id:
                continue
            if topic["parent_topic_id"] == topic_id:
                topic = {**topic, "parent_topic_id": None}  # will be promoted
            remaining.append(topic)
        reassigned = reassign_notes_to_topics(plan["notes"], remaining)
        assignments = reassigned["assignments"]
        mode = reassigned["mode"]
        # Notes no topic fits wait in Needs you with their likeliest topics.
        from app.organizer import topic_choices

        choices_for = {
            note["id"]: [topic["id"] for topic in topic_choices(note.get("text") or "", remaining, limit=2)]
            for note in plan["notes"]
            if not assignments.get(note["id"])
        }
    else:
        choices_for = {}
    try:
        outcome = delete_topic_in_db(topic_id, assignments, choices_for)
    except TopicConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to delete topic")
        raise HTTPException(
            status_code=500,
            detail="Unable to delete topic. Please try again.",
        ) from exc
    if outcome is None:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return {**outcome, "mode": mode}


@app.patch("/api/topics/{topic_id}", response_model=Topic)
def patch_topic(topic_id: int, payload: TopicUpdate):
    bot_key = _life_area(payload.bot_key)
    try:
        topic = update_topic_in_db(
            topic_id,
            name=payload.name.strip() if payload.name else None,
            description=payload.description,
            archived=payload.archived,
            bot_key=bot_key,
        )
    except TopicConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to update topic")
        raise HTTPException(
            status_code=500,
            detail="Unable to update topic. Please try again.",
        ) from exc
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return topic


@app.get("/api/items/{item_id}/insight", response_model=ItemInsight)
def read_item_insight(item_id: int):
    try:
        insight = get_item_insight(item_id)
    except Exception as exc:
        logger.exception("Failed to load item insight")
        raise HTTPException(
            status_code=500,
            detail="Unable to load insight. Please try again.",
        ) from exc
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found.")
    return insight


@app.patch("/api/items/{item_id}/insight", response_model=ItemInsight)
def patch_item_insight(item_id: int, payload: InsightOverrideUpdate):
    try:
        insight = update_item_insight_overrides(
            item_id,
            user_title=payload.user_title,
            user_topic_id=payload.user_topic_id,
            user_priority=payload.user_priority,
            user_tags=payload.user_tags,
            clear_overrides=payload.clear_overrides,
            needs_review=payload.needs_review,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to update item insight")
        raise HTTPException(
            status_code=500,
            detail="Unable to update insight. Please try again.",
        ) from exc
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found.")
    return insight


@app.get("/api/relations", response_model=List[ItemRelation])
def get_relations(include_dismissed: bool = Query(False)):
    try:
        return list_relations_from_db(include_dismissed=include_dismissed)
    except Exception as exc:
        logger.exception("Failed to load relations")
        raise HTTPException(
            status_code=500,
            detail="Unable to load related items. Please try again.",
        ) from exc


@app.post("/api/relations/{relation_id}/dismiss", response_model=ItemRelation)
def dismiss_relation(relation_id: int):
    try:
        relation = dismiss_relation_in_db(relation_id)
    except Exception as exc:
        logger.exception("Failed to dismiss relation")
        raise HTTPException(
            status_code=500,
            detail="Unable to dismiss relation. Please try again.",
        ) from exc
    if relation is None:
        raise HTTPException(status_code=404, detail="Relation not found.")
    return relation


@app.get("/api/search", response_model=list[SearchHit])
def search_inbox(
    q: str = Query(..., min_length=1, max_length=200),
    item_type: Optional[str] = Query(None, max_length=100),
    limit: int = Query(8, ge=1, le=25),
    bot: Optional[str] = Query(None, max_length=20),
):
    bot = _life_area(bot)
    try:
        ranked = search_passages(
            q,
            limit=limit,
            item_type=item_type,
            item_ids=item_ids_for_bot(bot) if bot else None,
        )
    except Exception as exc:
        logger.exception("Search failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to search inbox. Please try again.",
        ) from exc
    return [
        SearchHit(
            item_id=row.passage.item_id,
            item_type=row.passage.item_type,
            title=mask_secrets(row.passage.title),
            excerpt=mask_secrets(row.passage.passage[:320]),
            source_kind=row.passage.source_kind,
            preview_url=row.passage.preview_url,
            score=round(row.score, 4),
            keyword_score=round(row.keyword_score, 4),
            semantic_score=round(row.semantic_score, 4),
        )
        for row in ranked
    ]


@app.post("/api/ask", response_model=AskResponse)
def ask_my_inbox(payload: AskRequest):
    bot = _life_area(payload.bot)  # an unknown area is a 422, not a failure
    try:
        return build_grounded_answer(
            payload.question.strip(),
            item_type=payload.item_type,
            bot=bot,
        )
    except Exception as exc:
        logger.exception("Ask My Inbox failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to answer from your inbox. Please try again.",
        ) from exc


@app.get("/api/dashboard")
def organization_dashboard():
    try:
        return get_organization_dashboard()
    except Exception as exc:
        logger.exception("Failed to load organization dashboard")
        raise HTTPException(
            status_code=500,
            detail="Unable to load dashboard. Please try again.",
        ) from exc


@app.get(
    "/api/analyze/latest",
    response_model=PersistedAnalysis,
)
def get_latest_analysis():
    try:
        result = get_latest_successful_analysis()
    except Exception as exc:
        logger.exception("Failed to load latest analysis")
        raise HTTPException(
            status_code=500,
            detail="Unable to load the latest analysis. Please try again.",
        ) from exc

    if result is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return result


@app.get("/api/captain/greeting", response_model=Greeting)
def captain_greeting(background_tasks: BackgroundTasks):
    """Captain's greeting (change 020, decision N): the day's AI line once it
    exists, else code's while it's written in the background (one call a day).
    Also starts the weekly review after 7 days, when the scheduler hasn't."""
    import app.review as review
    from app.attention.dates import today_in_configured_tz
    from app.database import get_settings, require_owner_id

    user_id = require_owner_id()
    day = today_in_configured_tz().isoformat()
    found = review.greeting(user_id, day)
    if found["write"]:
        background_tasks.add_task(review.write_greeting, user_id, day)
    if review.review_due(get_settings(user_id)):
        background_tasks.add_task(review.run_weekly, user_id)
    return {"text": found["text"], "ai": found["ai"]}


@app.get("/api/bots/{bot_key}/summary", response_model=BotSummary)
def area_summary(bot_key: str, background_tasks: BackgroundTasks):
    """An area's summary: the saved one until the area changes, then one call."""
    import app.review as review
    from app.database import require_owner_id

    key = _life_area(bot_key)
    if key is None:
        raise HTTPException(status_code=422, detail="Unknown life area.")
    user_id = require_owner_id()
    found = review.bot_summary(key, user_id)
    if found["rewrite"]:
        background_tasks.add_task(review.rewrite_summary, key, user_id)
    return {"bot_key": key, "summary": found["summary"], "ai": found["ai"]}


@app.get("/api/scout", response_model=ScoutState)
def read_scout():
    """Scout's questions now (change 018). Also notes that you're here, so
    "You've been away 9 days" can be said after a break. No AI call."""
    import app.scout as scout

    return scout.state(mark_seen=True)


@app.post("/api/scout/finish", response_model=ScoutState)
def finish_scout():
    import app.scout as scout

    return scout.finish()


@app.post("/api/scout/bulk", response_model=ScoutResult)
def scout_bulk(payload: ScoutBulk):
    import app.scout as scout

    return scout.run_bulk(payload.which)


@app.post("/api/scout/{question_id}/answer", response_model=ScoutResult)
def answer_scout(question_id: str, payload: ScoutAnswer):
    import app.scout as scout

    try:
        return scout.answer(question_id, payload.action, due_on=payload.due_on.isoformat() if payload.due_on else None,
                            due_time=payload.due_time, reason=payload.reason)
    except scout.QuestionGone as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/someday", response_model=Task)
def change_task_someday(task_id: int, payload: TaskSomeday):
    """Move a task to Someday (its date goes), or back to your lists."""
    from app.database import set_task_someday

    if not set_task_someday([task_id], payload.someday):
        raise HTTPException(status_code=404, detail="Task not found.")
    task = next((task for task in list_tasks_from_db("open") if task["id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.get("/api/settings", response_model=UserSettings)
def read_settings():
    from app.database import get_settings

    return get_settings()


@app.patch("/api/settings", response_model=UserSettings)
def change_settings(payload: UserSettingsUpdate):
    """Health-memory consent (016; off forgets health facts), the AI switch
    (025), the weekly catch-up day and time (018)."""
    from app.database import update_settings

    changes = {key: value for key, value in payload.model_dump().items() if value is not None}
    return update_settings(**changes)


@app.get("/api/memory", response_model=MemoryView)
def read_memory(bot: Optional[str] = Query(None, max_length=20)):
    """What Life Inbox learned about you: one area's facts (`bot`), Captain's
    (bot="captain": across areas), or all; plus what's coming up."""
    from app.database import get_settings, list_memory, upcoming_plans

    if bot not in (None, "", "captain") and bot not in BOT_KEYS:
        raise HTTPException(status_code=422, detail="Unknown life area.")
    facts = list_memory(bot="" if bot == "captain" else bot)
    return {"facts": facts, "coming_up": upcoming_plans(), "health_memory_consent": get_settings()["health_memory_consent"]}


@app.patch("/api/memory/{fact_id}", response_model=MemoryFact)
def change_memory(fact_id: int, payload: MemoryUpdate):
    from app.database import update_memory

    try:
        fact = update_memory(fact_id, text=payload.text, status=payload.status, core_profile=payload.core_profile)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if fact is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return fact


@app.delete("/api/memory/{fact_id}", status_code=204)
def forget_memory(fact_id: int):
    """Forget a fact: its text is erased, and it's never suggested again."""
    from app.database import delete_memory

    if not delete_memory(fact_id):
        raise HTTPException(status_code=404, detail="Not found.")
    return Response(status_code=204)


@app.get("/api/items/{item_id}/ideas", response_model=List[TaskIdea])
def get_item_ideas(item_id: int):
    """The maybes and someday ideas found in a note (change 014a)."""
    from app.database import list_ideas

    if get_item_from_db(item_id) is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return list_ideas(item_id=item_id, status="waiting")


@app.post("/api/ideas/{idea_id}/add", response_model=Task)
def add_idea(idea_id: int):
    """Turn an idea into a real task."""
    from app.database import add_idea_as_task

    task = add_idea_as_task(idea_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Idea not found.")
    return task


@app.get("/api/captain/needs-you", response_model=NeedsYouList)
def get_needs_you():
    """Captain's "Needs you" list (change 013): ranked, at most one card per
    note, worked out by code from your data (no AI call)."""
    return captain.needs_you()


@app.post("/api/captain/needs-you/{card_id}/resolve", response_model=NeedsYouList)
def resolve_needs_you(card_id: str, payload: NeedsYouResolve):
    """Answer a card ("Not now", a pick, Drop it, Add a note, Delete, Done).
    The answer is kept so the card doesn't come back. Returns the new list."""
    try:
        return captain.resolve(card_id, payload.action, payload.value)
    except captain.CardGone as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/analyze", response_model=PersistedAnalysis)
def analyze_inbox(item_id: Optional[int] = Query(None)):
    """File a note you just saved (change 014: one checked AI call; notes saved
    while a call runs share the next one). Without `item_id`: "Re-sort
    everything", 25 notes per call (see GET /api/filing/resort-plan first)."""
    try:
        if item_id is not None:
            if not get_note_from_db(item_id):
                raise HTTPException(
                    status_code=404, detail="Item not found or not analyzable."
                )
            return filing.file_items([item_id])
        outcome = filing.resort_all()
        if outcome["analysis"] is None:
            raise HTTPException(status_code=404, detail="There are no notes to re-sort.")
        return outcome["analysis"]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to file notes")
        raise HTTPException(
            status_code=500,
            detail="Unable to analyze inbox. Please try again.",
        ) from exc


@app.get("/api/filing/resort-plan", response_model=ResortPlan)
def get_resort_plan():
    """How many notes "Re-sort everything" would re-file, and how many AI calls
    that takes (25 notes per call). Notes you filed yourself are left alone."""
    return filing.resort_plan()


@app.post("/api/filing/resort", response_model=ResortResult)
def resort_everything():
    """Re-file every note you didn't file yourself, only when you ask."""
    outcome = filing.resort_all()
    return {key: outcome[key] for key in ("notes", "calls", "waiting", "retired_catch_all")}


@app.post("/api/topics/{topic_id}/recheck", response_model=TopicRecheck)
def recheck_topic(topic_id: int):
    """After creating a topic: re-check only the notes whose words fit it (at
    most 25, so 0-1 call). Returns the notes that moved in, for Undo."""
    try:
        return filing.recheck_for_topic(topic_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Topic not found.") from exc


@app.post("/api/filing/undo-moves")
def undo_topic_moves_endpoint(payload: TopicMovesUndo):
    """Undo "Moved N notes into Python": put them back where they were."""
    from app.database import undo_topic_moves

    restored = undo_topic_moves([move.model_dump() for move in payload.moves])
    return {"restored": restored}


def _template(name: str) -> str:
    return (APP_DIR / "templates" / name).read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index():
    return _template("index.html")


@app.get("/service-worker.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        APP_DIR / "static" / "service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if getattr(request.state, "user", None) is not None:
        return RedirectResponse("/", status_code=302)
    return _template("login.html")


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page():
    return _template("privacy.html")


@app.get("/terms", response_class=HTMLResponse)
def terms_page():
    return _template("terms.html")
