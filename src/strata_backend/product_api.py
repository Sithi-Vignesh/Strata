"""FastAPI transport boundary for the Strata product service."""

import logging
from collections.abc import Callable

from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from strata_backend.product_schemas import (
    AddWorkspaceMember,
    CreateNote,
    CreateProject,
    CreateTask,
    CreateWorkspace,
    NoteResponse,
    OwnershipTransferResponse,
    LoginRequest,
    RegisterAccount,
    ProjectResponse,
    TaskResponse,
    UpdateNote,
    UpdateProject,
    UpdateTask,
    UpdateUser,
    UpdateWorkspace,
    TransferWorkspaceOwnership,
    UserResponse,
    WorkspaceMemberResponse,
    WorkspaceResponse,
)
from strata_backend.product_auth import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    set_session_cookie,
)
from strata_backend.product_models import User
from strata_backend.product_service import (
    ProductConflictError,
    ProductNotFoundError,
    ProductPermissionError,
    ProductService,
    ProductServiceError,
    ProductValidationError,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def get_product_service(request: Request) -> ProductService:
    """Retrieve the lifespan-owned product service for the current application."""
    return request.app.state.product_service


def _authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTHENTICATION_REQUIRED", "message": "Authentication required."},
    )


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "INVALID_CREDENTIALS", "message": "Invalid credentials."},
    )


def _cookie_secure(request: Request) -> bool:
    return bool(request.app.state.session_cookie_secure)


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    service: ProductService = Depends(get_product_service),
) -> User:
    """Resolve an ACTIVE user from the opaque browser session cookie."""
    if session_token is None:
        raise _authentication_required()
    session = service.find_session_by_token(session_token)
    if session is None:
        raise _authentication_required()
    try:
        user = service.get_user(session.user_id)
    except ProductServiceError:
        raise _authentication_required() from None
    if user.account_state != "ACTIVE":
        raise _authentication_required()
    return user


def register_product_exception_handlers(application: FastAPI) -> None:
    """Install shared ProductService-to-HTTP exception translations."""
    handlers: tuple[tuple[type[ProductServiceError], int, str], ...] = (
        (ProductNotFoundError, status.HTTP_404_NOT_FOUND, "PRODUCT_NOT_FOUND"),
        (ProductConflictError, status.HTTP_409_CONFLICT, "PRODUCT_CONFLICT"),
        (ProductValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT, "PRODUCT_VALIDATION_ERROR"),
        (ProductPermissionError, status.HTTP_403_FORBIDDEN, "PRODUCT_PERMISSION_DENIED"),
    )
    for exception_type, status_code, code in handlers:
        application.add_exception_handler(
            exception_type,
            _domain_exception_handler(status_code, code),
        )
    application.add_exception_handler(ProductServiceError, _internal_service_error_handler)


def _domain_exception_handler(
    status_code: int, code: str,
) -> Callable[[Request, ProductServiceError], JSONResponse]:
    async def handler(_: Request, exc: ProductServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"detail": {"code": code, "message": str(exc)}},
        )

    return handler


async def _internal_service_error_handler(_: Request, exc: ProductServiceError) -> JSONResponse:
    logger.exception("Unexpected product service failure", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": {"code": "INTERNAL_ERROR", "message": "Internal product service error."}},
    )


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_account(
    body: RegisterAccount,
    request: Request,
    response: Response,
    service: ProductService = Depends(get_product_service),
) -> object:
    registered = service.register_account(body.name, body.email, body.password)
    set_session_cookie(response, registered.token, secure=_cookie_secure(request))
    return registered.user


@router.post("/auth/login", response_model=UserResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: ProductService = Depends(get_product_service),
) -> object:
    authenticated = service.authenticate_user(body.email, body.password)
    if authenticated is None:
        raise _invalid_credentials()
    set_session_cookie(response, authenticated.token, secure=_cookie_secure(request))
    return service.get_user(authenticated.session.user_id)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    service: ProductService = Depends(get_product_service),
) -> Response:
    if session_token is not None:
        session = service.find_session_by_token(session_token)
        if session is not None:
            try:
                service.revoke_session(session.id)
            except ProductServiceError:
                pass
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, secure=_cookie_secure(request))
    return response


@router.get("/auth/me", response_model=UserResponse)
def get_authenticated_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.get_user(user_id, actor_user_id=current_user.id)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, body: UpdateUser, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.update_user(user_id, actor_user_id=current_user.id, **_provided_fields(body))


@router.get("/users/{user_id}/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces_for_user(user_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.list_workspaces_for_user(user_id, actor_user_id=current_user.id)


@router.post("/workspaces", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(body: CreateWorkspace, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.create_workspace(body.name, current_user.id)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(workspace_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.get_workspace(workspace_id, actor_user_id=current_user.id)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int, body: UpdateWorkspace, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service),
) -> object:
    return service.update_workspace(workspace_id, actor_user_id=current_user.id, **_provided_fields(body))


@router.delete("/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> Response:
    service.delete_workspace(workspace_id, actor_user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_workspace_members(workspace_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return [_member_response(member, service) for member in service.list_workspace_members(workspace_id, actor_user_id=current_user.id)]


@router.post("/workspaces/{workspace_id}/members", response_model=WorkspaceMemberResponse, status_code=status.HTTP_201_CREATED)
def add_workspace_member(
    workspace_id: int, body: AddWorkspaceMember, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service),
) -> object:
    return _member_response(service.add_workspace_member(workspace_id, body.user_id, actor_user_id=current_user.id), service)


@router.post("/workspaces/{workspace_id}/transfer-ownership", response_model=OwnershipTransferResponse)
def transfer_workspace_ownership(
    workspace_id: int, body: TransferWorkspaceOwnership, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service),
) -> object:
    previous_owner_id, owner_id = service.transfer_workspace_ownership(workspace_id, body.new_owner_user_id, actor_user_id=current_user.id)
    return {"workspace_id": workspace_id, "owner_user_id": owner_id, "previous_owner_user_id": previous_owner_id}


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workspace_member(
    workspace_id: int, user_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service),
) -> Response:
    service.remove_workspace_member(workspace_id, user_id, actor_user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectResponse])
def list_projects(workspace_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.list_projects(workspace_id, actor_user_id=current_user.id)


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    workspace_id: int, body: CreateProject, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service),
) -> object:
    return service.create_project(workspace_id, body.name, body.description, actor_user_id=current_user.id)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.get_project(project_id, actor_user_id=current_user.id)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, body: UpdateProject, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.update_project(project_id, actor_user_id=current_user.id, **_provided_fields(body))


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> Response:
    service.delete_project(project_id, actor_user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskResponse])
def list_tasks(project_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.list_tasks(project_id, actor_user_id=current_user.id)


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(project_id: int, body: CreateTask, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.create_task(
        project_id,
        body.title,
        description=body.description,
        status=body.status,
        priority=body.priority,
        assignee_user_id=body.assignee_user_id, actor_user_id=current_user.id,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.get_task(task_id, actor_user_id=current_user.id)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, body: UpdateTask, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.update_task(task_id, actor_user_id=current_user.id, **_provided_fields(body))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> Response:
    service.delete_task(task_id, actor_user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tasks/{task_id}/notes", response_model=list[NoteResponse])
def list_notes(task_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.list_notes(task_id, actor_user_id=current_user.id)


@router.post("/tasks/{task_id}/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(task_id: int, body: CreateNote, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.create_note(task_id, current_user.id, body.content, actor_user_id=current_user.id)


@router.get("/notes/{note_id}", response_model=NoteResponse)
def get_note(note_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.get_note(note_id, actor_user_id=current_user.id)


@router.patch("/notes/{note_id}", response_model=NoteResponse)
def update_note(note_id: int, body: UpdateNote, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> object:
    return service.update_note(note_id, actor_user_id=current_user.id, **_provided_fields(body))


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, current_user: User = Depends(get_current_user), service: ProductService = Depends(get_product_service)) -> Response:
    service.delete_note(note_id, actor_user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _provided_fields(body: object) -> dict[str, object]:
    """Return only PATCH fields explicitly supplied by the client, including nulls."""
    return {field: getattr(body, field) for field in body.model_fields_set}  # type: ignore[attr-defined]


def _member_response(member: object, service: ProductService) -> dict[str, object]:
    """Return only safe identity fields for an authorized workspace membership."""
    user = service.get_user(member.user_id)  # type: ignore[attr-defined]
    return {
        "workspace_id": member.workspace_id, "user_id": member.user_id, "role": member.role,  # type: ignore[attr-defined]
        "name": user.name, "email": user.email, "account_state": user.account_state,
    }
