import requests
import json
import time
import subprocess

# Codespaces içindeki hazır GitHub token'ını otomatik al
token = ""
try:
    token = subprocess.check_output(["gh", "auth", "token"]).decode("utf-8").strip()
except Exception:
    pass

headers = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "RepoSkeleton-App"
}
if token:
    headers["Authorization"] = f"Bearer {token}"
    print("🔑 GitHub Token tespit edildi, yüksek API limiti devrede.")
else:
    print("⚠️ Token bulunamadı, genel kotayla çekiliyor...")

QUERY = "stars:500..5000 pushed:<2025-01-01 license:mit archived:false"
BASE_URL = "https://api.github.com/search/repositories"

all_repos = []
page = 1
max_pages = 10  # GitHub arama API'si maksimum 1000 sonuç (10 sayfa x 100) verir

print("🚀 Kriterlere uyan tüm repolar taranıyor...")

while page <= max_pages:
    url = f"{BASE_URL}?q={QUERY}&sort=stars&order=desc&per_page=100&page={page}"
    print(f"📦 Sayfa {page} çekiliyor (Şu ana kadar toplanan: {len(all_repos)})...")
    
    res = requests.get(url, headers=headers)
    
    if res.status_code == 200:
        items = res.json().get("items", [])
        if not items:
            break
            
        for r in items:
            all_repos.append({
                "name": r["name"],
                "full_name": r["full_name"],
                "language": r["language"] or "Diğer",
                "stars": r["stargazers_count"],
                "issues": r["open_issues_count"],
                "last_push": r["pushed_at"][:10],
                "url": r["html_url"],
                "description": r["description"] or "Açıklama belirtilmemiş.",
                "votes": int(r["stargazers_count"] / 10)
            })
            
        page += 1
        time.sleep(1.5)  # API limitine takılmamak için kısa bekleme
    elif res.status_code == 403:
        print("⚠️ GitHub API hız sınırına ulaşıldı. Mevcut veriler kaydediliyor...")
        break
    else:
        print(f"Hata: {res.status_code}")
        break

# Sonuçları kaydet
with open("repos.json", "w", encoding="utf-8") as f:
    json.dump(all_repos, f, ensure_ascii=False, indent=2)

print(f"\n🎉 İşlem tamamlandı! Toplam {len(all_repos)} adet fırsat 'repos.json' dosyasına kaydedildi.")
