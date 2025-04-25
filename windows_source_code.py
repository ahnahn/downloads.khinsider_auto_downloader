import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
import os, time, sys
from tqdm import tqdm
import argparse
import re

# 실행 파일 위치를 기준 경로로 사용
if getattr(sys, 'frozen', False):
    # PyInstaller로 빌드된 exe에서
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 스크립트로 실행할 때
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(BASE_DIR)  # 작업 디렉토리를 exe 위치로 변경

def sanitize(name):
    # 파일명에 쓸 수 없는 문자는 모두 '-' 로 치환
    return re.sub(r'[\\/:"*?<>|]+', '-', name).strip()

def parse_args():
    p = argparse.ArgumentParser(
        description="Khinsider 앨범 페이지에서 고해상도 이미지 + FLAC 일괄 다운로드"
    )
    p.add_argument("-u", "--url", help="앨범 페이지 URL")
    p.add_argument("-o", "--out", help="저장 폴더 이름 (기본: 앨범 제목)")
    args, _ = p.parse_known_args()
    return args


def main():
    args = parse_args()
    album_url = args.url or input("앨범 URL을 입력하세요: ").strip()

    # 웹 요청 세션 초기화
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    resp = session.get(album_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 앨범 제목으로 폴더명 결정
    raw_title = soup.title.string or ""
    album_title = sanitize(raw_title.split(" - ")[0])
    out_name = args.out or album_title
    download_dir = os.path.join(BASE_DIR, out_name)
    os.makedirs(download_dir, exist_ok=True)
    print(f"[INFO] 앨범: {album_title}\n[INFO] 저장 폴더: {download_dir}")

    # 이미지 다운로드
    images_dir = os.path.join(download_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    print("[INFO] 이미지 링크 수집 및 다운로드 시작")

    for thumb in tqdm(soup.select("a img"), desc="이미지"):
        a = thumb.find_parent("a", href=True)
        if not a:
            continue
        href = a["href"]
        # 관련 없는 앨범 링크 건너뛰기
        if "/game-soundtracks/album/" in href:
            continue
        page = urljoin(album_url, href)

        if page.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
            highres_url = page
        else:
            r2 = session.get(page, headers={"Referer": album_url})
            r2.raise_for_status()
            sub = BeautifulSoup(r2.text, "html.parser")
            img2 = next((cand for cand in sub.find_all("img")
                         if cand.get("src", "").lower().endswith((".jpg", ".jpeg", ".png", ".gif"))), None)
            if not img2:
                continue
            highres_url = urljoin(page, img2["src"])

        fname = sanitize(unquote(os.path.basename(highres_url)))
        fpath = os.path.join(images_dir, fname)
        if not os.path.exists(fpath):
            with session.get(highres_url, headers={"Referer": page}, stream=True) as r3:
                if r3.status_code == 200:
                    with open(fpath, "wb") as w:
                        for chunk in r3.iter_content(8192):
                            w.write(chunk)

    # FLAC 다운로드
    table = None
    for tbl in soup.find_all("table"):
        hdr = [th.get_text(strip=True) for th in tbl.find_all("th")]
        if "Song Name" in hdr and "FLAC" in hdr:
            table = tbl
            break
    if not table:
        print("[ERROR] 앨범 트랙 테이블을 찾을 수 없습니다.")
        return

    track_links = []
    for row in table.find_all("tr")[1:]:
        tds = row.find_all("td")
        if len(tds) >= 6:
            a = tds[5].find("a", href=True)
            if a:
                track_links.append(urljoin(album_url, a["href"]))
    print(f"[INFO] 총 {len(track_links)}곡 FLAC 다운로드 시작")

    for link in tqdm(track_links, desc="트랙"):
        time.sleep(0.3)
        if link.lower().endswith(".flac"):
            flac_url = link
        else:
            r = session.get(link, headers={"Referer": album_url})
            r.raise_for_status()
            tag = sub = BeautifulSoup(r.text, "html.parser").select_one("a[href$='.flac']")
            if not tag:
                continue
            flac_url = urljoin(link, tag["href"])

        fname = sanitize(unquote(os.path.basename(flac_url)))
        fpath = os.path.join(download_dir, fname)
        if not os.path.exists(fpath):
            with session.get(flac_url, headers={"Referer": link}, stream=True) as dl:
                if dl.status_code == 200:
                    with open(fpath, "wb") as fw:
                        for chunk in dl.iter_content(8192):
                            fw.write(chunk)

    print("✅ 모든 이미지 및 FLAC 다운로드 완료!")

if __name__ == "__main__":
    main()
