from fastapi import FastAPI, Request, Body, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import requests
import json
import os

CLIENT_ID = "Ov23likHyNMrjv1u5NL1"
CLIENT_SECRET = "5ef3fc5201fd58c8d3e821de886e7c5139120ba1"

app = FastAPI()

from fastapi.responses import FileResponse

@app.api_route("/favicon.svg", methods=["GET", "HEAD"])
@app.get("/favicon.ico")
def get_favicon():
    return FileResponse("favicon.svg", media_type="image/svg+xml")


import os
import json
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
DATA_FILE = "discussions.json"

def init_db():
    if not DATABASE_URL:
        return
    try:
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS store (
                        key TEXT PRIMARY KEY,
                        value JSONB
                    );
                """)
                conn.commit()
    except Exception as e:
        print("DB init error:", e)

init_db()

def load_data():
    if DATABASE_URL:
        try:
            db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT value FROM store WHERE key = 'discussions'")
                    row = cur.fetchone()
                    if row and row[0]:
                        return row[0]
                    return {}
        except Exception as e:
            print("DB load error:", e)
            return {}
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_data(data):
    if DATABASE_URL:
        try:
            db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO store (key, value)
                        VALUES ('discussions', %s)
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
                    """, (json.dumps(data),))
                    conn.commit()
            return
        except Exception as e:
            print("DB save error:", e)
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("File save error:", e)




@app.get("/login")
def login():
    github_auth_url = f"https://github.com/login/oauth/authorize?client_id={CLIENT_ID}&scope=read:user,public_repo,public_repo"
    return RedirectResponse(github_auth_url)

@app.get("/callback")
def callback(code: str):
    token_url = "https://github.com/login/oauth/access_token"
    res = requests.post(token_url, headers={"Accept": "application/json"}, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code
    }).json()

    access_token = res.get("access_token")
    if not access_token:
        return HTMLResponse("GitHub Authentication failed.", status_code=400)

    user_res = requests.get("https://api.github.com/user", headers={
        "Authorization": f"Bearer {access_token}"
    }).json()

    username = user_res.get("login", "")
    avatar = user_res.get("avatar_url", "")
    return RedirectResponse(f"/?token={access_token}&user={username}&avatar={avatar}")

def normalize_repo_data(repo_data):
    if "revivers" not in repo_data:
        revivers = []
        old_claim = repo_data.get("claimed_by")
        old_url = repo_data.get("revived_url")
        if old_claim:
            revivers.append({"user": old_claim, "fork_url": old_url})
        repo_data["revivers"] = revivers
    return repo_data

@app.post("/api/fork")
async def fork_repo(request: Request):
    payload = await request.json()
    repo = payload.get("repo")
    token = request.session.get("token") or payload.get("token")
    user = request.session.get("user") or payload.get("user")

    if isinstance(user, dict):
        user = user.get("login") or user.get("username")

    if not token or not repo or not user:
        return JSONResponse({"error": "Unauthorized or missing repo"}, status_code=400)

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    res = requests.post(f"https://api.github.com/repos/{repo}/forks", headers=headers)

    if res.status_code in [200, 202]:
        fork_url = res.json().get("html_url")
        all_data = load_data()
        repo_data = normalize_repo_data(all_data.get(repo, {"status": "dormant", "claimed_by": None, "revived_url": None, "comments": []}))
        
        # Kullanıcı zaten revivers listesinde yoksa ekle
        if not any(r.get("user") == user for r in repo_data["revivers"]):
            repo_data["revivers"].append({"user": user, "fork_url": fork_url})
        
        repo_data["status"] = "wip"
        repo_data["claimed_by"] = repo_data["revivers"][0]["user"] if repo_data["revivers"] else user
        repo_data["revived_url"] = fork_url
        
        all_data[repo] = repo_data
        save_data(all_data)
        return {"success": True, "fork_url": fork_url, "data": repo_data}
    else:
        return JSONResponse({"error": res.json().get("message", "Fork failed")}, status_code=400)

@app.post("/api/status")
async def update_status(request: Request):
    payload = await request.json()
    repo = payload.get("repo")
    status = payload.get("status") # dormant, wip, revived
    raw_user = payload.get("user") or payload.get("username")
    if isinstance(raw_user, dict):
        user = raw_user.get("login") or raw_user.get("username")
    else:
        user = str(raw_user).strip() if raw_user else None
    revived_url = payload.get("revived_url", "").strip()

    if not repo or not status or not user:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    all_data = load_data()
    repo_data = normalize_repo_data(all_data.get(repo, {"status": "dormant", "claimed_by": None, "revived_url": None, "comments": []}))

    if status == "dormant":
        # Biri dormant dediğinde sadece o kullanıcı listeden çıkar
        repo_data["revivers"] = [r for r in repo_data["revivers"] if r.get("user") != user]
        if len(repo_data["revivers"]) == 0:
            repo_data["status"] = "dormant"
            repo_data["claimed_by"] = None
        else:
            repo_data["status"] = "wip"
            repo_data["claimed_by"] = repo_data["revivers"][0]["user"]
    elif status == "wip":
        if not any(r.get("user") == user for r in repo_data["revivers"]):
            repo_data["revivers"].append({"user": user, "fork_url": revived_url or None})
        repo_data["status"] = "wip"
        repo_data["claimed_by"] = user
    elif status == "revived":
        if not any(r.get("user") == user for r in repo_data["revivers"]):
            repo_data["revivers"].append({"user": user, "fork_url": revived_url or None})
        repo_data["status"] = "revived"
        if revived_url:
            repo_data["revived_url"] = revived_url

    all_data[repo] = repo_data
    save_data(all_data)
    return {"success": True, "data": repo_data}

@app.post("/api/comments")
async def post_comment(request: Request):
    payload = await request.json()
    repo = payload.get("repo")
    user = payload.get("user")
    avatar = payload.get("avatar")
    text = payload.get("text")

    if not repo or not text or not user:
        return JSONResponse({"error": "Invalid data"}, status_code=400)

    all_data = load_data()
    repo_data = all_data.get(repo, {"status": "dormant", "claimed_by": None, "revived_url": None, "comments": []})

    comment_obj = {
        "id": os.urandom(4).hex(),
        "user": user,
        "avatar": avatar,
        "text": text,
        "votes": 0,
        "time": "Just now"
    }
    repo_data["comments"].insert(0, comment_obj)
    all_data[repo] = repo_data
    save_data(all_data)

    return {"success": True, "comment": comment_obj}

@app.post("/api/comments/vote")
async def vote_comment(request: Request):
    payload = await request.json()
    repo = payload.get("repo")
    comment_id = payload.get("comment_id")
    delta = int(payload.get("delta", 1))

    all_data = load_data()
    repo_data = all_data.get(repo)
    if not repo_data:
        return JSONResponse({"error": "Repo not found"}, status_code=404)

    for c in repo_data.get("comments", []):
        if c.get("id") == comment_id:
            c["votes"] = c.get("votes", 0) + delta
            save_data(all_data)
            return {"success": True, "votes": c["votes"]}

    return JSONResponse({"error": "Comment not found"}, status_code=404)

@app.get("/repos.json")
def get_repos():
    if os.path.exists("repos.json"):
        with open("repos.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return []

@app.get("/", response_class=HTMLResponse)
def index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html not found</h1>"

from fastapi.responses import HTMLResponse

@app.get("/api/user/{username}")
def get_user_profile(username: str):
    """Kullanıcının durum güncellemelerini, sahiplendiği projeleri ve yorumlarını çeker."""
    discussions = load_data()
    
    revived_repos = []
    wip_repos = []
    user_comments = []
    u_lower = username.lower()
    
    for repo_full_name, data in discussions.items():
        raw_status = data.get("status")
        claimed_by = None
        state = None
        revived_url = data.get("revived_url")

        if isinstance(raw_status, dict):
            claimed_by = raw_status.get("updated_by") or raw_status.get("claimed_by") or raw_status.get("user")
            state = (raw_status.get("state") or raw_status.get("status") or "").lower()
            revived_url = raw_status.get("revived_url") or revived_url
        elif isinstance(raw_status, str):
            state = raw_status.lower()
            claimed_by = data.get("claimed_by") or data.get("user") or data.get("username")

        # claimed_by dict ise login'i al
        if isinstance(claimed_by, dict):
            claimed_by = claimed_by.get("login") or claimed_by.get("username")

        if claimed_by and claimed_by.lower() == u_lower:
            repo_entry = {
                "repo": repo_full_name,
                "status": "Revived" if state == "revived" else ("WIP" if state == "wip" else state.capitalize()),
                "revived_url": revived_url,
                "updated_at": data.get("updated_at")
            }
            if state == "revived":
                revived_repos.append(repo_entry)
            elif state == "wip":
                wip_repos.append(repo_entry)
                
        for comment in data.get("comments", []):
            if comment.get("user", "").lower() == u_lower:
                user_comments.append({
                    "repo": repo_full_name,
                    "text": comment.get("text"),
                    "votes": comment.get("votes", 0),
                    "created_at": comment.get("created_at")
                })
                
    return {
        "username": username,
        "revived_count": len(revived_repos),
        "wip_count": len(wip_repos),
        "total_comments": len(user_comments),
        "revived_repos": revived_repos,
        "wip_repos": wip_repos,
        "comments": user_comments
    }

@app.get("/u/{username}", response_class=HTMLResponse)
def user_profile_page(username: str):
    """Profil sayfası arayüzü"""
    with open("profile.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/api/fork/{owner}/{repo}")
def fork_repository(owner: str, repo: str, request_data: dict = Body(...)):
    token = request_data.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    # GitHub Fork API çağrısı
    url = f"https://api.github.com/repos/{owner}/{repo}/forks"
    res = requests.post(url, headers=headers)
    
    if res.status_code in [200, 202]:
        fork_data = res.json()
        return {
            "success": True,
            "html_url": fork_data.get("html_url"),
            "full_name": fork_data.get("full_name")
        }
    else:
        return {
            "success": False,
            "error": res.json().get("message", "GitHub Fork API error"),
            "status_code": res.status_code
        }
