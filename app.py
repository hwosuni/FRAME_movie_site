import os
import requests
from pathlib import Path
from flask import Flask, render_template, request
from dotenv import load_dotenv

load_dotenv(override=True)
print("ENV 파일 존재:", (Path(__file__).resolve().parent / ".env").exists())
print("ENV 파일 경로:", Path(__file__).resolve().parent / ".env")
print("ENV 파일 내용:", repr(Path(__file__).resolve().parent.joinpath(".env").read_text(encoding="utf-8")))
app = Flask(__name__)

TMDB_API_KEY = os.getenv("TMDB_API_KEY")

print("API 키 읽기 성공:", bool(TMDB_API_KEY))

GENRE_IDS = {
    "액션": 28,
    "코미디": 35,
    "드라마": 18,
    "SF": 878,
    "미스터리": 9648,
    "스릴러": 53,
    "판타지": 14,
    "로맨스": 10749,
    "애니메이션": 16,
    "공포": 27
}


@app.route("/", methods=["GET", "POST"])
def home():
    movies = []
    error = None

    if request.method == "POST":
        genres = request.form.getlist("genres")

        genre_ids = [
            GENRE_IDS[g] for g in genres if g in GENRE_IDS
        ]

        if not TMDB_API_KEY:
            error = ".env 파일에서 API 키를 찾지 못했습니다."

        elif not genre_ids:
            error = "장르를 하나 이상 선택해주세요."

        else:
            try:
                response = requests.get(
                    "https://api.themoviedb.org/3/discover/movie",
                    params={
                        "api_key": TMDB_API_KEY,
                        "language": "ko-KR",
                        "with_genres": ",".join(map(str, genre_ids)),
                        "sort_by": "popularity.desc",
                        "page": 1
                    },
                    timeout=15
                )

                response.raise_for_status()
                movies = response.json().get("results", [])

                for movie in movies:
                    movie["genre_names"] = [
                        name for name, genre_id in GENRE_IDS.items()
                        if genre_id in movie.get("genre_ids", [])
                    ]

            except requests.exceptions.RequestException as e:
                print(e)
                error = "TMDB 연결에 실패했습니다. API 키와 인터넷을 확인해주세요."
    print("요청 방식:", request.method)
    print("영화 개수:", len(movies))

    return render_template(
        "index.html",
        submitted=bool(movies),
        preferences=None,
        movies=movies,
        error=error
    )


if __name__ == "__main__":
    app.run(debug=True)
