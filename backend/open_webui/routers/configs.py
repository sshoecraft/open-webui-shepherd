import logging
import copy
import os
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
import aiohttp

from typing import Optional

from open_webui.env import DATA_DIR

from open_webui.env import AIOHTTP_CLIENT_TIMEOUT
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.config import get_config, save_config
from open_webui.config import BannerModel

from open_webui.utils.tools import (
    get_tool_server_data,
    get_tool_server_url,
    set_tool_servers,
)
from open_webui.utils.mcp.client import MCPClient
from open_webui.utils.shepherd.client import ShepherdClient
from open_webui.models.oauth_sessions import OAuthSessions


from open_webui.utils.oauth import (
    get_discovery_urls,
    get_oauth_client_info_with_dynamic_client_registration,
    encrypt_data,
    decrypt_data,
    OAuthClientInformationFull,
)
from mcp.shared.auth import OAuthMetadata

router = APIRouter()

log = logging.getLogger(__name__)


############################
# ImportConfig
############################


class ImportConfigForm(BaseModel):
    config: dict


@router.post("/import", response_model=dict)
async def import_config(form_data: ImportConfigForm, user=Depends(get_admin_user)):
    save_config(form_data.config)
    return get_config()


############################
# ExportConfig
############################


@router.get("/export", response_model=dict)
async def export_config(user=Depends(get_admin_user)):
    return get_config()


############################
# Connections Config
############################


class ConnectionsConfigForm(BaseModel):
    ENABLE_DIRECT_CONNECTIONS: bool
    ENABLE_BASE_MODELS_CACHE: bool


@router.get("/connections", response_model=ConnectionsConfigForm)
async def get_connections_config(request: Request, user=Depends(get_admin_user)):
    return {
        "ENABLE_DIRECT_CONNECTIONS": request.app.state.config.ENABLE_DIRECT_CONNECTIONS,
        "ENABLE_BASE_MODELS_CACHE": request.app.state.config.ENABLE_BASE_MODELS_CACHE,
    }


@router.post("/connections", response_model=ConnectionsConfigForm)
async def set_connections_config(
    request: Request,
    form_data: ConnectionsConfigForm,
    user=Depends(get_admin_user),
):
    request.app.state.config.ENABLE_DIRECT_CONNECTIONS = (
        form_data.ENABLE_DIRECT_CONNECTIONS
    )
    request.app.state.config.ENABLE_BASE_MODELS_CACHE = (
        form_data.ENABLE_BASE_MODELS_CACHE
    )

    return {
        "ENABLE_DIRECT_CONNECTIONS": request.app.state.config.ENABLE_DIRECT_CONNECTIONS,
        "ENABLE_BASE_MODELS_CACHE": request.app.state.config.ENABLE_BASE_MODELS_CACHE,
    }


class OAuthClientRegistrationForm(BaseModel):
    url: str
    client_id: str
    client_name: Optional[str] = None


@router.post("/oauth/clients/register")
async def register_oauth_client(
    request: Request,
    form_data: OAuthClientRegistrationForm,
    type: Optional[str] = None,
    user=Depends(get_admin_user),
):
    try:
        oauth_client_id = form_data.client_id
        if type:
            oauth_client_id = f"{type}:{form_data.client_id}"

        oauth_client_info = (
            await get_oauth_client_info_with_dynamic_client_registration(
                request, oauth_client_id, form_data.url
            )
        )
        return {
            "status": True,
            "oauth_client_info": encrypt_data(
                oauth_client_info.model_dump(mode="json")
            ),
        }
    except Exception as e:
        log.debug(f"Failed to register OAuth client: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to register OAuth client",
        )


############################
# ToolServers Config
############################


class ToolServerConnection(BaseModel):
    url: str
    path: str
    type: Optional[str] = "openapi"  # openapi, mcp
    auth_type: Optional[str]
    headers: Optional[dict | str] = None
    key: Optional[str]
    config: Optional[dict]

    model_config = ConfigDict(extra="allow")


class ToolServersConfigForm(BaseModel):
    TOOL_SERVER_CONNECTIONS: list[ToolServerConnection]


@router.get("/tool_servers", response_model=ToolServersConfigForm)
async def get_tool_servers_config(request: Request, user=Depends(get_admin_user)):
    return {
        "TOOL_SERVER_CONNECTIONS": request.app.state.config.TOOL_SERVER_CONNECTIONS,
    }


@router.post("/tool_servers", response_model=ToolServersConfigForm)
async def set_tool_servers_config(
    request: Request,
    form_data: ToolServersConfigForm,
    user=Depends(get_admin_user),
):
    for connection in request.app.state.config.TOOL_SERVER_CONNECTIONS:
        server_type = connection.get("type", "openapi")
        auth_type = connection.get("auth_type", "none")

        if auth_type == "oauth_2.1":
            # Remove existing OAuth clients for tool servers
            server_id = connection.get("info", {}).get("id")
            client_key = f"{server_type}:{server_id}"

            try:
                request.app.state.oauth_client_manager.remove_client(client_key)
            except:
                pass

    # Set new tool server connections
    request.app.state.config.TOOL_SERVER_CONNECTIONS = [
        connection.model_dump() for connection in form_data.TOOL_SERVER_CONNECTIONS
    ]

    await set_tool_servers(request)

    for connection in request.app.state.config.TOOL_SERVER_CONNECTIONS:
        server_type = connection.get("type", "openapi")
        if server_type == "mcp":
            server_id = connection.get("info", {}).get("id")
            auth_type = connection.get("auth_type", "none")

            if auth_type == "oauth_2.1" and server_id:
                try:
                    oauth_client_info = connection.get("info", {}).get(
                        "oauth_client_info", ""
                    )
                    oauth_client_info = decrypt_data(oauth_client_info)

                    request.app.state.oauth_client_manager.add_client(
                        f"{server_type}:{server_id}",
                        OAuthClientInformationFull(**oauth_client_info),
                    )
                except Exception as e:
                    log.debug(f"Failed to add OAuth client for MCP tool server: {e}")
                    continue

    return {
        "TOOL_SERVER_CONNECTIONS": request.app.state.config.TOOL_SERVER_CONNECTIONS,
    }


@router.post("/tool_servers/verify")
async def verify_tool_servers_config(
    request: Request, form_data: ToolServerConnection, user=Depends(get_admin_user)
):
    """
    Verify the connection to the tool server.
    """
    try:
        if form_data.type == "mcp":
            if form_data.auth_type == "oauth_2.1":
                discovery_urls = get_discovery_urls(form_data.url)
                for discovery_url in discovery_urls:
                    log.debug(
                        f"Trying to fetch OAuth 2.1 discovery document from {discovery_url}"
                    )
                    async with aiohttp.ClientSession(
                        trust_env=True,
                        timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
                    ) as session:
                        async with session.get(
                            discovery_url
                        ) as oauth_server_metadata_response:
                            if oauth_server_metadata_response.status == 200:
                                try:
                                    oauth_server_metadata = (
                                        OAuthMetadata.model_validate(
                                            await oauth_server_metadata_response.json()
                                        )
                                    )
                                    return {
                                        "status": True,
                                        "oauth_server_metadata": oauth_server_metadata.model_dump(
                                            mode="json"
                                        ),
                                    }
                                except Exception as e:
                                    log.info(
                                        f"Failed to parse OAuth 2.1 discovery document: {e}"
                                    )
                                    raise HTTPException(
                                        status_code=400,
                                        detail=f"Failed to parse OAuth 2.1 discovery document from {discovery_url}",
                                    )

                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to fetch OAuth 2.1 discovery document from {discovery_urls}",
                )
            else:
                try:
                    client = MCPClient()
                    headers = None

                    token = None
                    if form_data.auth_type == "bearer":
                        token = form_data.key
                    elif form_data.auth_type == "session":
                        token = request.state.token.credentials
                    elif form_data.auth_type == "system_oauth":
                        oauth_token = None
                        try:
                            if request.cookies.get("oauth_session_id", None):
                                oauth_token = await request.app.state.oauth_manager.get_oauth_token(
                                    user.id,
                                    request.cookies.get("oauth_session_id", None),
                                )

                                if oauth_token:
                                    token = oauth_token.get("access_token", "")
                        except Exception as e:
                            pass
                    if token:
                        headers = {"Authorization": f"Bearer {token}"}

                    if form_data.headers and isinstance(form_data.headers, dict):
                        if headers is None:
                            headers = {}
                        headers.update(form_data.headers)

                    await client.connect(form_data.url, headers=headers)
                    specs = await client.list_tool_specs()
                    return {
                        "status": True,
                        "specs": specs,
                    }
                except Exception as e:
                    log.debug(f"Failed to create MCP client: {e}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to create MCP client",
                    )
                finally:
                    if client:
                        await client.disconnect()
        elif form_data.type == "shepherd":
            try:
                client = ShepherdClient()
                headers = None

                token = None
                if form_data.auth_type == "bearer":
                    token = form_data.key
                elif form_data.auth_type == "session":
                    token = request.state.token.credentials
                elif form_data.auth_type == "system_oauth":
                    oauth_token = None
                    try:
                        if request.cookies.get("oauth_session_id", None):
                            oauth_token = await request.app.state.oauth_manager.get_oauth_token(
                                user.id,
                                request.cookies.get("oauth_session_id", None),
                            )

                            if oauth_token:
                                token = oauth_token.get("access_token", "")
                    except Exception:
                        pass
                if token:
                    headers = {"Authorization": f"Bearer {token}"}

                if form_data.headers and isinstance(form_data.headers, dict):
                    if headers is None:
                        headers = {}
                    headers.update(form_data.headers)

                await client.connect(form_data.url, headers=headers)
                specs = await client.list_tool_specs()
                return {
                    "status": True,
                    "specs": specs,
                }
            except Exception as e:
                log.debug(f"Failed to create Shepherd client: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to connect to Shepherd server",
                )
            finally:
                if client:
                    await client.disconnect()
        else:  # openapi
            token = None
            headers = None
            if form_data.auth_type == "bearer":
                token = form_data.key
            elif form_data.auth_type == "session":
                token = request.state.token.credentials
            elif form_data.auth_type == "system_oauth":
                try:
                    if request.cookies.get("oauth_session_id", None):
                        oauth_token = (
                            await request.app.state.oauth_manager.get_oauth_token(
                                user.id,
                                request.cookies.get("oauth_session_id", None),
                            )
                        )

                        if oauth_token:
                            token = oauth_token.get("access_token", "")

                except Exception as e:
                    pass

            if token:
                headers = {"Authorization": f"Bearer {token}"}

            if form_data.headers and isinstance(form_data.headers, dict):
                if headers is None:
                    headers = {}
                headers.update(form_data.headers)

            url = get_tool_server_url(form_data.url, form_data.path)
            return await get_tool_server_data(url, headers=headers)
    except HTTPException as e:
        raise e
    except Exception as e:
        log.debug(f"Failed to connect to the tool server: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect to the tool server",
        )


############################
# CodeInterpreterConfig
############################
class CodeInterpreterConfigForm(BaseModel):
    ENABLE_CODE_EXECUTION: bool
    CODE_EXECUTION_ENGINE: str
    CODE_EXECUTION_JUPYTER_URL: Optional[str]
    CODE_EXECUTION_JUPYTER_AUTH: Optional[str]
    CODE_EXECUTION_JUPYTER_AUTH_TOKEN: Optional[str]
    CODE_EXECUTION_JUPYTER_AUTH_PASSWORD: Optional[str]
    CODE_EXECUTION_JUPYTER_TIMEOUT: Optional[int]
    ENABLE_CODE_INTERPRETER: bool
    CODE_INTERPRETER_ENGINE: str
    CODE_INTERPRETER_PROMPT_TEMPLATE: Optional[str]
    CODE_INTERPRETER_JUPYTER_URL: Optional[str]
    CODE_INTERPRETER_JUPYTER_AUTH: Optional[str]
    CODE_INTERPRETER_JUPYTER_AUTH_TOKEN: Optional[str]
    CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD: Optional[str]
    CODE_INTERPRETER_JUPYTER_TIMEOUT: Optional[int]


@router.get("/code_execution", response_model=CodeInterpreterConfigForm)
async def get_code_execution_config(request: Request, user=Depends(get_admin_user)):
    return {
        "ENABLE_CODE_EXECUTION": request.app.state.config.ENABLE_CODE_EXECUTION,
        "CODE_EXECUTION_ENGINE": request.app.state.config.CODE_EXECUTION_ENGINE,
        "CODE_EXECUTION_JUPYTER_URL": request.app.state.config.CODE_EXECUTION_JUPYTER_URL,
        "CODE_EXECUTION_JUPYTER_AUTH": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH,
        "CODE_EXECUTION_JUPYTER_AUTH_TOKEN": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
        "CODE_EXECUTION_JUPYTER_AUTH_PASSWORD": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
        "CODE_EXECUTION_JUPYTER_TIMEOUT": request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT,
        "ENABLE_CODE_INTERPRETER": request.app.state.config.ENABLE_CODE_INTERPRETER,
        "CODE_INTERPRETER_ENGINE": request.app.state.config.CODE_INTERPRETER_ENGINE,
        "CODE_INTERPRETER_PROMPT_TEMPLATE": request.app.state.config.CODE_INTERPRETER_PROMPT_TEMPLATE,
        "CODE_INTERPRETER_JUPYTER_URL": request.app.state.config.CODE_INTERPRETER_JUPYTER_URL,
        "CODE_INTERPRETER_JUPYTER_AUTH": request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH,
        "CODE_INTERPRETER_JUPYTER_AUTH_TOKEN": request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH_TOKEN,
        "CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD": request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD,
        "CODE_INTERPRETER_JUPYTER_TIMEOUT": request.app.state.config.CODE_INTERPRETER_JUPYTER_TIMEOUT,
    }


@router.post("/code_execution", response_model=CodeInterpreterConfigForm)
async def set_code_execution_config(
    request: Request, form_data: CodeInterpreterConfigForm, user=Depends(get_admin_user)
):

    request.app.state.config.ENABLE_CODE_EXECUTION = form_data.ENABLE_CODE_EXECUTION

    request.app.state.config.CODE_EXECUTION_ENGINE = form_data.CODE_EXECUTION_ENGINE
    request.app.state.config.CODE_EXECUTION_JUPYTER_URL = (
        form_data.CODE_EXECUTION_JUPYTER_URL
    )
    request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH = (
        form_data.CODE_EXECUTION_JUPYTER_AUTH
    )
    request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN = (
        form_data.CODE_EXECUTION_JUPYTER_AUTH_TOKEN
    )
    request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD = (
        form_data.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD
    )
    request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT = (
        form_data.CODE_EXECUTION_JUPYTER_TIMEOUT
    )

    request.app.state.config.ENABLE_CODE_INTERPRETER = form_data.ENABLE_CODE_INTERPRETER
    request.app.state.config.CODE_INTERPRETER_ENGINE = form_data.CODE_INTERPRETER_ENGINE
    request.app.state.config.CODE_INTERPRETER_PROMPT_TEMPLATE = (
        form_data.CODE_INTERPRETER_PROMPT_TEMPLATE
    )

    request.app.state.config.CODE_INTERPRETER_JUPYTER_URL = (
        form_data.CODE_INTERPRETER_JUPYTER_URL
    )

    request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH = (
        form_data.CODE_INTERPRETER_JUPYTER_AUTH
    )

    request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH_TOKEN = (
        form_data.CODE_INTERPRETER_JUPYTER_AUTH_TOKEN
    )
    request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD = (
        form_data.CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD
    )
    request.app.state.config.CODE_INTERPRETER_JUPYTER_TIMEOUT = (
        form_data.CODE_INTERPRETER_JUPYTER_TIMEOUT
    )

    return {
        "ENABLE_CODE_EXECUTION": request.app.state.config.ENABLE_CODE_EXECUTION,
        "CODE_EXECUTION_ENGINE": request.app.state.config.CODE_EXECUTION_ENGINE,
        "CODE_EXECUTION_JUPYTER_URL": request.app.state.config.CODE_EXECUTION_JUPYTER_URL,
        "CODE_EXECUTION_JUPYTER_AUTH": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH,
        "CODE_EXECUTION_JUPYTER_AUTH_TOKEN": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
        "CODE_EXECUTION_JUPYTER_AUTH_PASSWORD": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
        "CODE_EXECUTION_JUPYTER_TIMEOUT": request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT,
        "ENABLE_CODE_INTERPRETER": request.app.state.config.ENABLE_CODE_INTERPRETER,
        "CODE_INTERPRETER_ENGINE": request.app.state.config.CODE_INTERPRETER_ENGINE,
        "CODE_INTERPRETER_PROMPT_TEMPLATE": request.app.state.config.CODE_INTERPRETER_PROMPT_TEMPLATE,
        "CODE_INTERPRETER_JUPYTER_URL": request.app.state.config.CODE_INTERPRETER_JUPYTER_URL,
        "CODE_INTERPRETER_JUPYTER_AUTH": request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH,
        "CODE_INTERPRETER_JUPYTER_AUTH_TOKEN": request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH_TOKEN,
        "CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD": request.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD,
        "CODE_INTERPRETER_JUPYTER_TIMEOUT": request.app.state.config.CODE_INTERPRETER_JUPYTER_TIMEOUT,
    }


############################
# SetDefaultModels
############################
class ModelsConfigForm(BaseModel):
    DEFAULT_MODELS: Optional[str] = None
    DEFAULT_PINNED_MODELS: Optional[str] = None
    MODEL_ORDER_LIST: Optional[list[str]] = None
    ENABLE_MODEL_SELECTOR: Optional[bool] = None
    ENABLE_INTEGRATIONS_MENU: Optional[bool] = None
    ENABLE_CHAT_CONTROLS: Optional[bool] = None
    ENABLE_TEMPORARY_CHAT: Optional[bool] = None


@router.get("/models", response_model=ModelsConfigForm)
async def get_models_config(request: Request, user=Depends(get_admin_user)):
    return {
        "DEFAULT_MODELS": request.app.state.config.DEFAULT_MODELS,
        "DEFAULT_PINNED_MODELS": request.app.state.config.DEFAULT_PINNED_MODELS,
        "MODEL_ORDER_LIST": request.app.state.config.MODEL_ORDER_LIST,
        "ENABLE_MODEL_SELECTOR": request.app.state.config.ENABLE_MODEL_SELECTOR,
        "ENABLE_INTEGRATIONS_MENU": request.app.state.config.ENABLE_INTEGRATIONS_MENU,
        "ENABLE_CHAT_CONTROLS": request.app.state.config.ENABLE_CHAT_CONTROLS,
        "ENABLE_TEMPORARY_CHAT": request.app.state.config.ENABLE_TEMPORARY_CHAT,
    }


@router.post("/models", response_model=ModelsConfigForm)
async def set_models_config(
    request: Request, form_data: ModelsConfigForm, user=Depends(get_admin_user)
):
    if form_data.DEFAULT_MODELS is not None:
        request.app.state.config.DEFAULT_MODELS = form_data.DEFAULT_MODELS
    if form_data.DEFAULT_PINNED_MODELS is not None:
        request.app.state.config.DEFAULT_PINNED_MODELS = form_data.DEFAULT_PINNED_MODELS
    if form_data.MODEL_ORDER_LIST is not None:
        request.app.state.config.MODEL_ORDER_LIST = form_data.MODEL_ORDER_LIST
    if form_data.ENABLE_MODEL_SELECTOR is not None:
        request.app.state.config.ENABLE_MODEL_SELECTOR = form_data.ENABLE_MODEL_SELECTOR
    if form_data.ENABLE_INTEGRATIONS_MENU is not None:
        request.app.state.config.ENABLE_INTEGRATIONS_MENU = form_data.ENABLE_INTEGRATIONS_MENU
    if form_data.ENABLE_CHAT_CONTROLS is not None:
        request.app.state.config.ENABLE_CHAT_CONTROLS = form_data.ENABLE_CHAT_CONTROLS
    if form_data.ENABLE_TEMPORARY_CHAT is not None:
        request.app.state.config.ENABLE_TEMPORARY_CHAT = form_data.ENABLE_TEMPORARY_CHAT
    return {
        "DEFAULT_MODELS": request.app.state.config.DEFAULT_MODELS,
        "DEFAULT_PINNED_MODELS": request.app.state.config.DEFAULT_PINNED_MODELS,
        "MODEL_ORDER_LIST": request.app.state.config.MODEL_ORDER_LIST,
        "ENABLE_MODEL_SELECTOR": request.app.state.config.ENABLE_MODEL_SELECTOR,
        "ENABLE_INTEGRATIONS_MENU": request.app.state.config.ENABLE_INTEGRATIONS_MENU,
        "ENABLE_CHAT_CONTROLS": request.app.state.config.ENABLE_CHAT_CONTROLS,
        "ENABLE_TEMPORARY_CHAT": request.app.state.config.ENABLE_TEMPORARY_CHAT,
    }


class PromptSuggestion(BaseModel):
    title: list[str]
    content: str


class SetDefaultSuggestionsForm(BaseModel):
    suggestions: list[PromptSuggestion]


@router.post("/suggestions", response_model=list[PromptSuggestion])
async def set_default_suggestions(
    request: Request,
    form_data: SetDefaultSuggestionsForm,
    user=Depends(get_admin_user),
):
    data = form_data.model_dump()
    request.app.state.config.DEFAULT_PROMPT_SUGGESTIONS = data["suggestions"]
    return request.app.state.config.DEFAULT_PROMPT_SUGGESTIONS


############################
# SetBanners
############################


class SetBannersForm(BaseModel):
    banners: list[BannerModel]


@router.post("/banners", response_model=list[BannerModel])
async def set_banners(
    request: Request,
    form_data: SetBannersForm,
    user=Depends(get_admin_user),
):
    data = form_data.model_dump()
    request.app.state.config.BANNERS = data["banners"]
    return request.app.state.config.BANNERS


@router.get("/banners", response_model=list[BannerModel])
async def get_banners(
    request: Request,
    user=Depends(get_verified_user),
):
    return request.app.state.config.BANNERS


############################
# Branding
############################


class BrandingConfigForm(BaseModel):
    CUSTOM_NAME: Optional[str] = None
    CUSTOM_LOGO: Optional[str] = None
    ENABLE_SPLASH_SCREEN: Optional[bool] = None


@router.get("/branding")
async def get_branding_config(request: Request, user=Depends(get_verified_user)):
    return {
        "CUSTOM_NAME": request.app.state.config.CUSTOM_NAME,
        "CUSTOM_LOGO": request.app.state.config.CUSTOM_LOGO,
        "ENABLE_SPLASH_SCREEN": request.app.state.config.ENABLE_SPLASH_SCREEN,
    }


@router.post("/branding")
async def set_branding_config(
    request: Request, form_data: BrandingConfigForm, user=Depends(get_admin_user)
):
    if form_data.CUSTOM_NAME is not None:
        request.app.state.config.CUSTOM_NAME = form_data.CUSTOM_NAME
    if form_data.CUSTOM_LOGO is not None:
        request.app.state.config.CUSTOM_LOGO = form_data.CUSTOM_LOGO
    if form_data.ENABLE_SPLASH_SCREEN is not None:
        request.app.state.config.ENABLE_SPLASH_SCREEN = form_data.ENABLE_SPLASH_SCREEN
    return {
        "CUSTOM_NAME": request.app.state.config.CUSTOM_NAME,
        "CUSTOM_LOGO": request.app.state.config.CUSTOM_LOGO,
        "ENABLE_SPLASH_SCREEN": request.app.state.config.ENABLE_SPLASH_SCREEN,
    }


@router.post("/branding/logo")
async def upload_branding_logo(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(get_admin_user),
):
    """Upload a custom logo for branding."""
    # Create branding directory if it doesn't exist
    branding_dir = Path(DATA_DIR) / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)

    # Validate file type
    allowed_types = ["image/png", "image/jpeg", "image/svg+xml", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}",
        )

    # Save file as logo with appropriate extension
    ext = file.filename.split(".")[-1] if "." in file.filename else "png"
    logo_path = branding_dir / f"logo.{ext}"

    # Remove any existing logo files
    for existing in branding_dir.glob("logo.*"):
        existing.unlink()

    # Save the new logo
    with open(logo_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Update config to point to the logo
    relative_path = f"branding/logo.{ext}"
    request.app.state.config.CUSTOM_LOGO = relative_path

    return {"CUSTOM_LOGO": relative_path}


@router.get("/branding/logo")
async def get_branding_logo(request: Request):
    """Serve the custom logo if it exists, otherwise return default."""
    custom_logo = request.app.state.config.CUSTOM_LOGO
    if custom_logo:
        logo_path = Path(DATA_DIR) / custom_logo
        if logo_path.exists():
            return FileResponse(logo_path)

    # Return 404 if no custom logo - frontend will use default
    raise HTTPException(status_code=404, detail="No custom logo configured")


@router.delete("/branding/logo")
async def delete_branding_logo(
    request: Request,
    user=Depends(get_admin_user),
):
    """Delete the custom logo and revert to default."""
    branding_dir = Path(DATA_DIR) / "branding"

    # Remove any existing logo files
    for existing in branding_dir.glob("logo.*"):
        existing.unlink()

    # Clear the config
    request.app.state.config.CUSTOM_LOGO = ""

    return {"CUSTOM_LOGO": ""}
