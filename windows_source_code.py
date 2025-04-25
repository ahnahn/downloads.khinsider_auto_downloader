import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
import os, time, sys
from tqdm import tqdm
import argparse
import re
import ctypes
import ctypes.wintypes
import traceback

# 토스트 알림용
from win10toast import ToastNotifier
toaster = ToastNotifier()

# 실행 파일 위치 기준
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

def sanitize(name):
    return re.sub(r'[\\/:"*?<>|]+', '-', name).strip()

def parse_args():
    p = argparse.ArgumentParser(description="Khinsider 앨범 페이지에서 이미지 + FLAC 다운로드")
    p.add_argument("-u", "--url", help="앨범 페이지 URL")
    p.add_argument("-o", "--out", help="저장 폴더 이름 (기본: 앨범 제목)")
    args, _ = p.parse_known_args()
    return args

def flash_taskbar():
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = kernel32.GetConsoleWindow()
    if hwnd:
        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.UINT),
                ("hwnd", ctypes.wintypes.HWND),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("uCount", ctypes.wintypes.UINT),
                ("dwTimeout", ctypes.wintypes.DWORD),
            ]
        FLASHW_ALL = 3
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_ALL, 5, 0)
        user32.FlashWindowEx(ctypes.byref(info))

def notify_toast(title: str, msg: str, duration: int = 8):
    toaster.show_toast(title, msg, duration=duration, threaded=True)

def download_album(album_url, custom_out=None):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    resp = session.get(album_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    raw_title = soup.title.string or ""
    album_title = sanitize(raw_title.replace(" MP3", "").split(" - ")[0])
    out_name = custom_out or album_title
    download_dir = os.path.join(BASE_DIR, out_name)
    os.makedirs(download_dir, exist_ok=True)
    print(f"\n[INFO] 앨범: {album_title}\n[INFO] 저장 폴더: {download_dir}")

    # 1) 이미지 다운로드
    images_dir = os.path.join(download_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    print("[INFO] 이미지 링크 수집 및 다운로드 시작")
    for thumb in tqdm(soup.select("a img"), desc="이미지"):
        a = thumb.find_parent("a", href=True)
        if not a:
            continue
        href = a["href"]
        if "/game-soundtracks/album/" in href:
            continue
        page = urljoin(album_url, href)

        if page.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
            highres_url = page
        else:
            r2 = session.get(page, headers={"Referer": album_url}, timeout=30)
            r2.raise_for_status()
            sub = BeautifulSoup(r2.text, "html.parser")
            img2 = next((img for img in sub.find_all("img")
                         if img.get("src", "").lower().endswith((".jpg", ".jpeg", ".png", ".gif"))), None)
            if not img2:
                continue
            highres_url = urljoin(page, img2["src"])

        fname = sanitize(unquote(os.path.basename(highres_url)))
        fpath = os.path.join(images_dir, fname)
        if not os.path.exists(fpath):
            r3 = session.get(highres_url, headers={"Referer": page}, stream=True, timeout=30)
            r3.raise_for_status()
            with open(fpath, "wb") as w:
                for chunk in r3.iter_content(8192):
                    w.write(chunk)

    # 2) 트랙 테이블 찾기
    table = None
    for tbl in soup.find_all("table"):
        hdr = [th.get_text(strip=True) for th in tbl.find_all("th")]
        if "Song Name" in hdr and "FLAC" in hdr:
            table = tbl
            break
    if not table:
        raise RuntimeError("앨범 트랙 테이블을 찾을 수 없습니다.")

    # 3) 트랙 링크 수집
    track_links = []
    for row in table.find_all("tr")[1:]:
        tds = row.find_all("td")
        if len(tds) >= 6:
            a = tds[5].find("a", href=True)
            if a:
                track_links.append(urljoin(album_url, a["href"]))
    print(f"[INFO] 총 {len(track_links)}곡 FLAC 다운로드 시작")

    # 4) FLAC 다운로드
    for link in tqdm(track_links, desc="트랙"):
        time.sleep(2)
        if link.lower().endswith(".flac"):
            flac_url = link
        else:
            r = session.get(link, headers={"Referer": album_url}, timeout=30)
            r.raise_for_status()
            tag = BeautifulSoup(r.text, "html.parser").select_one("a[href$='.flac']")
            if not tag:
                raise RuntimeError(f"FLAC 링크를 찾을 수 없음: {link}")
            flac_url = urljoin(link, tag["href"])

        fname = sanitize(unquote(os.path.basename(flac_url)))
        fpath = os.path.join(download_dir, fname)
        if os.path.exists(fpath):
            continue  # 이미 다운로드된 파일 스킵

        r = session.get(flac_url, headers={"Referer": link}, stream=True, timeout=60)
        r.raise_for_status()
        with open(fpath, "wb") as fw:
            for chunk in r.iter_content(8192):
                fw.write(chunk)

    print("✅ 모든 이미지 및 FLAC 다운로드 완료!")
    flash_taskbar()
    notify_toast("Khinsider 다운로더", f"✅ '{album_title}' 다운로드 완료!", duration=8)

if __name__ == "__main__":
    try:
        args = parse_args()
        while True:
            url = args.url or input("\n앨범 URL을 입력하세요 (종료하려면 Ctrl+C): ").strip()
            success = False
            while not success:
                try:
                    download_album(url, args.out)
                    success = True
                    args.url = None
                except Exception as e:
                    print("\n❌ 오류 발생:", e)
                    traceback.print_exc()
                    flash_taskbar()
                    notify_toast("Khinsider 다운로더", f"❌ 오류 발생:\n{e}", duration=8)
                    print("\n⚠️ 오류가 발생했지만 같은 URL로 다시 시도합니다...")
                    time.sleep(2)
    except KeyboardInterrupt:
        print("\n종료합니다.")
