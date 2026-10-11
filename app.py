from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import requests
import json
import os

CLIENT_ID = "Ov23likHyNMrjv1u5NL1"
CLIENT_SECRET = "5ef3fc5201fd58c8d3e821de886e7c5139120ba1"

app = FastAPI()

DATA_FILE = "discussions.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

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

@app.post("/api/fork")
async def fork_repo(request: Request):
    data = await request.json()
    token = data.get("token")
    repo = data.get("repo")
    user = data.get("user")

    if not token or not repo:
        return JSONResponse({"error": "Missing token or repo"}, status_code=400)

    res = requests.post(f"https://api.github.com/repos/{repo}/forks", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    })

    if res.status_code in [200, 202]:
        forked_data = res.json()
        fork_url = forked_data.get("html_url")

        # Otomatik olarak repo durumunu WIP'e çek
        all_data = load_data()
        repo_data = all_data.get(repo, {"status": "dormant", "claimed_by": None, "revived_url": None, "comments": []})
        repo_data["status"] = "wip"
        repo_data["claimed_by"] = user
        if not repo_data.get("revived_url"):
            repo_data["revived_url"] = fork_url
        all_data[repo] = repo_data
        save_data(all_data)

        return {"success": True, "fork_url": fork_url}
    else:
        return JSONResponse({"error": res.json().get("message", "Fork failed")}, status_code=400)

@app.get("/api/discussions")
def get_discussions():
    return load_data()

@app.post("/api/update-status")
async def update_status(request: Request):
    payload = await request.json()
    repo = payload.get("repo")
    status = payload.get("status") # dormant, wip, revived
    user = payload.get("user")
    revived_url = payload.get("revived_url", "").strip()

    if not repo or not status or not user:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    all_data = load_data()
    repo_data = all_data.get(repo, {"status": "dormant", "claimed_by": None, "revived_url": None, "comments": []})
    
    repo_data["status"] = status
    repo_data["claimed_by"] = user if status != "dormant" else None
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
    discussions = load_discussions()
    
    # Kullanıcının güncellediği veya canlandırdığı projeler
    revived_repos = []
    wip_repos = []
    user_comments = []
    
    for repo_full_name, data in discussions.items():
        # Durum kontrolü
        status_info = data.get("status", {})
        if status_info.get("updated_by", "").lower() == username.lower():
            repo_entry = {
                "repo": repo_full_name,
                "status": status_info.get("state"),
                "revived_url": status_info.get("revived_url"),
                "updated_at": status_info.get("updated_at")
            }
            if status_info.get("state") == "Revived":
                revived_repos.append(repo_entry)
            elif status_info.get("state") == "WIP":
                wip_repos.append(repo_entry)
                
        # Yorum kontrolü
        for comment in data.get("comments", []):
            if comment.get("user", "").lower() == username.lower():
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
