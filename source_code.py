#Available on Google colab

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
import os, time
from tqdm import tqdm
import argparse
import re

def sanitize(name):
    # 파일명에 쓸 수 없는 문자는 모두 '-' 로 치환
    return re.sub(r'[\\/:"*?<>|]+', '-', name).strip()

def parse_args():
    p = argparse.ArgumentParser(
        description="Khinsider 앨범 페이지에서 고해상도 이미지 + FLAC 일괄 다운로드"
    )
    p.add_argument("-u", "--url", help="앨범 페이지 URL")
    p.add_argument("-o", "--out", help="저장 폴더 이름 (기본: 앨범 제목)")
    args, _ = p.parse_known_args()  # Colab/Jupyter -f 인자 무시
    return args

def main():
    args = parse_args()
    album_url = args.url or input("앨범 URL을 입력하세요: ").strip()

    # 세션 & 페이지 로드
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    resp = session.get(album_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 앨범 제목 추출 → 폴더명
    raw_title = soup.title.string or ""
    album_title = sanitize(raw_title.split(" - ")[0])
    download_dir = args.out or album_title
    os.makedirs(download_dir, exist_ok=True)
    print(f"[INFO] 앨범: {album_title}\n[INFO] 저장 폴더: {download_dir}")

    # 0) 고해상도 이미지 다운로드
    images_dir = os.path.join(download_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    print("[INFO] 이미지 링크 수집 및 다운로드 시작")
    # 썸네일 <img> 들을 감싸는 <a> 태그만 뽑아서 처리
    for thumb in tqdm(soup.select("a img"), desc="이미지"):
        a = thumb.find_parent("a", href=True)
        if not a:
            continue

        # === 추가된 필터링: 추천 앨범 링크 건너뛰기 ===
        a_href = a["href"]
        if "/game-soundtracks/album/" in a_href:
            continue
        # ============================================

        page = urljoin(album_url, a_href)

        # 1) 바로 이미지 파일 URL 인지?
        if page.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
            highres_url = page
        else:
            # 2) 상세 페이지 열어 첫 이미지(src가 이미지 확장자) 찾기
            r2 = session.get(page, headers={"Referer": album_url})
            r2.raise_for_status()
            sub = BeautifulSoup(r2.text, "html.parser")
            img2 = None
            for cand in sub.find_all("img"):
                src = cand.get("src", "")
                if src.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
                    img2 = cand
                    break
            if not img2:
                print(f"[SKIP IMG] 고해상도 이미지 없음: {page}")
                continue
            highres_url = urljoin(page, img2["src"])

        # 다운로드
        fname = sanitize(unquote(os.path.basename(highres_url)))
        fpath = os.path.join(images_dir, fname)
        if os.path.exists(fpath):
            continue
        with session.get(highres_url, headers={"Referer": page}, stream=True) as r3:
            if r3.status_code == 200:
                with open(fpath, "wb") as w:
                    for chunk in r3.iter_content(8192):
                        w.write(chunk)
            else:
                print(f"[ERROR IMG] {r3.status_code}: {highres_url}")

    # 1) 'Song Name' / 'FLAC' 테이블 찾기
    table = None
    for tbl in soup.find_all("table"):
        hdr = [th.get_text(strip=True) for th in tbl.find_all("th")]
        if "Song Name" in hdr and "FLAC" in hdr:
            table = tbl
            break
    if not table:
        print("[ERROR] 앨범 트랙 테이블을 찾을 수 없습니다.")
        return

    # 2) 6번째 <td> (FLAC 열) 의 <a> 링크 수집
    rows = table.find_all("tr")[1:]
    track_links = []
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 6:
            continue
        a = tds[5].find("a", href=True)
        if a:
            track_links.append(urljoin(album_url, a["href"]))

    print(f"[INFO] 총 {len(track_links)}곡 FLAC 다운로드 시작")

    # 3) 트랙 링크를 순회하며 .flac 파일 다운로드
    for link in tqdm(track_links, desc="트랙"):
        time.sleep(0.3)
        # 직접 .flac 파일인지
        if link.lower().endswith(".flac"):
            flac_url = link
        else:
            r = session.get(link, headers={"Referer": album_url})
            r.raise_for_status()
            sub = BeautifulSoup(r.text, "html.parser")
            tag = sub.select_one("a[href$='.flac']")
            if not tag:
                print(f"[SKIP] FLAC 링크 없음: {link}")
                continue
            flac_url = urljoin(link, tag["href"])

        raw_name = os.path.basename(flac_url)
        filename = sanitize(unquote(raw_name))
        fpath = os.path.join(download_dir, filename)
        if os.path.exists(fpath):
            continue

        with session.get(flac_url, headers={"Referer": link}, stream=True) as dl:
            if dl.status_code == 200:
                with open(fpath, "wb") as fw:
                    for chunk in dl.iter_content(8192):
                        fw.write(chunk)
            else:
                print(f"[ERROR] {dl.status_code}: {flac_url}")

    print("✅ 모든 이미지 및 FLAC 다운로드 완료!")

if __name__ == "__main__":
    main()
