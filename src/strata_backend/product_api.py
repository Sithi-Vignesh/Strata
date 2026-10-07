"""FastAPI transport boundary for the Strata product service."""

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from strata_backend.product_schemas import (
    CreateNote,
    CreateProject,
    CreateTask,
    CreateWorkspace,
    NoteResponse,
    RegisterAccount,
    ProjectResponse,
    TaskResponse,
    UpdateNote,
    UpdateProject,
    UpdateTask,
    UpdateUser,
    UpdateWorkspace,
    UserResponse,
    WorkspaceMemberResponse,
    WorkspaceResponse,
)
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
def register_account(body: RegisterAccount, service: ProductService = Depends(get_product_service)) -> object:
    return service.register_account(body.name, body.email, body.password).user


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.get_user(user_id)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, body: UpdateUser, service: ProductService = Depends(get_product_service)) -> object:
    return service.update_user(user_id, **_provided_fields(body))


@router.get("/users/{user_id}/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces_for_user(user_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.list_workspaces_for_user(user_id)


@router.post("/workspaces", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(body: CreateWorkspace, service: ProductService = Depends(get_product_service)) -> object:
    return service.create_workspace(body.name, body.owner_user_id)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(workspace_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.get_workspace(workspace_id)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int, body: UpdateWorkspace, service: ProductService = Depends(get_product_service),
) -> object:
    return service.update_workspace(workspace_id, **_provided_fields(body))


@router.delete("/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: int, service: ProductService = Depends(get_product_service)) -> Response:
    service.delete_workspace(workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_workspace_members(workspace_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.list_workspace_members(workspace_id)


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectResponse])
def list_projects(workspace_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.list_projects(workspace_id)


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    workspace_id: int, body: CreateProject, service: ProductService = Depends(get_product_service),
) -> object:
    return service.create_project(workspace_id, body.name, body.description)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.get_project(project_id)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, body: UpdateProject, service: ProductService = Depends(get_product_service)) -> object:
    return service.update_project(project_id, **_provided_fields(body))


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, service: ProductService = Depends(get_product_service)) -> Response:
    service.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskResponse])
def list_tasks(project_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.list_tasks(project_id)


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(project_id: int, body: CreateTask, service: ProductService = Depends(get_product_service)) -> object:
    return service.create_task(
        project_id,
        body.title,
        description=body.description,
        status=body.status,
        priority=body.priority,
        assignee_user_id=body.assignee_user_id,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.get_task(task_id)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, body: UpdateTask, service: ProductService = Depends(get_product_service)) -> object:
    return service.update_task(task_id, **_provided_fields(body))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, service: ProductService = Depends(get_product_service)) -> Response:
    service.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tasks/{task_id}/notes", response_model=list[NoteResponse])
def list_notes(task_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.list_notes(task_id)


@router.post("/tasks/{task_id}/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(task_id: int, body: CreateNote, service: ProductService = Depends(get_product_service)) -> object:
    return service.create_note(task_id, body.author_user_id, body.content)


@router.get("/notes/{note_id}", response_model=NoteResponse)
def get_note(note_id: int, service: ProductService = Depends(get_product_service)) -> object:
    return service.get_note(note_id)


@router.patch("/notes/{note_id}", response_model=NoteResponse)
def update_note(note_id: int, body: UpdateNote, service: ProductService = Depends(get_product_service)) -> object:
    return service.update_note(note_id, **_provided_fields(body))


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, service: ProductService = Depends(get_product_service)) -> Response:
    service.delete_note(note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _provided_fields(body: object) -> dict[str, object]:
    """Return only PATCH fields explicitly supplied by the client, including nulls."""
    return {field: getattr(body, field) for field in body.model_fields_set}  # type: ignore[attr-defined]
