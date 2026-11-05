
import os
import json
import requests
import sqlite3
import uuid
from datetime import datetime
from flask import Flask, render_template, request
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

DB_NAME = "frame.db"


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                recommendation_id TEXT PRIMARY KEY,
                preferences TEXT,
                movie_ids TEXT,
                suitability INTEGER,
                satisfaction INTEGER,
                comment TEXT,
                created_at TEXT
            )
        """)


init_db()

app = Flask(__name__)

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6.1-sol")

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


def recommend_movies(movies, preferences):
    if not movies:
        return []

    client = OpenAI(api_key=OPENAI_API_KEY)

    candidates = []

    for movie in movies[:10]:
        candidates.append({
            "id": movie["id"],
            "title": movie["title"],
            "overview": movie.get("overview", ""),
            "genres": movie["genre_names"],
            "release_date": movie.get("release_date", ""),
            "rating": movie.get("vote_average", 0)
        })

    prompt = f"""
너는 영화 추천 서비스 FRAME의 영화 추천 담당자야.

사용자의 취향:
{json.dumps(preferences, ensure_ascii=False)}

추천할 영화 후보:
{json.dumps(candidates, ensure_ascii=False)}

다음 규칙을 반드시 지켜.

1. 후보 영화에 포함된 영화만 추천해.
2. 영화의 줄거리와 장르에 근거해서 판단해.
3. 줄거리에 없는 내용을 추측해서 사실처럼 말하지 마.
4. 추가 요청을 가장 중요한 추천 기준으로 삼아.
5. 추가 요청에 명시된 배경, 소재, 상황 등을 충족하지 못하면 추천하지 마.
6. 피하고 싶은 요소가 뚜렷하게 포함된 영화는 제외해.
7. 추가 요청을 충족하는 영화 중 선호 장르와 보고 싶은 요소에 맞는 영화를 골라.
8. 추가 요청을 충족하는 영화가 5개보다 적으면 억지로 개수를 채우지 마.
9. 각 영화의 추천 이유는 구체적이고 간결하게 작성해.
10. 후보에 없는 영화 ID를 만들지 마.

반드시 다음 JSON 형식으로만 답변해.
다른 설명이나 마크다운은 쓰지 마.

{{
  "recommendations": [
    {{
      "movie_id": 123,
      "reason": "추천 이유"
    }}
  ]
}}
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=prompt
    )

    result = json.loads(response.output_text)

    movie_by_id = {movie["id"]: movie for movie in movies}
    recommended_movies = []

    for item in result.get("recommendations", []):
        movie = movie_by_id.get(item.get("movie_id"))

        if movie:
            movie["ai_reason"] = item.get("reason", "")
            recommended_movies.append(movie)

    return recommended_movies


def save_recommendation(recommendation_id, preferences, movies):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT INTO evaluations (
                recommendation_id, preferences, movie_ids, created_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            recommendation_id,
            json.dumps(preferences, ensure_ascii=False),
            json.dumps([movie["id"] for movie in movies]),
            datetime.now().isoformat(timespec="seconds")
        ))


def save_evaluation(recommendation_id, suitability, satisfaction, comment):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("""
            UPDATE evaluations
            SET suitability = ?, satisfaction = ?, comment = ?
            WHERE recommendation_id = ?
        """, (suitability, satisfaction, comment, recommendation_id))

        return cursor.rowcount > 0


@app.route("/rate", methods=["POST"])
def rate():
    try:
        recommendation_id = request.form.get("recommendation_id", "")
        suitability = int(request.form.get("suitability", 0))
        satisfaction = int(request.form.get("satisfaction", 0))
        comment = request.form.get("comment", "").strip()

        if not (1 <= suitability <= 5 and 1 <= satisfaction <= 5):
            return "평가 점수를 확인해주세요.", 400

        saved = save_evaluation(
            recommendation_id,
            suitability,
            satisfaction,
            comment
        )

        if not saved:
            return "평가 기록을 찾을 수 없습니다.", 404

        return render_template("thanks.html")

    except (ValueError, sqlite3.Error) as e:
        print("평가 저장 오류:", e)
        return "평가 저장에 실패했습니다.", 500


@app.route("/", methods=["GET", "POST"])
def home():
    movies = []
    error = None
    preferences = None
    recommendation_id = None

    if request.method == "POST":
        genres = request.form.getlist("genres")
        features = request.form.getlist("features")
        avoid = request.form.getlist("avoid")
        context = request.form.get("context", "상관없음")
        extra = request.form.get("extra", "").strip()

        genre_ids = [
            GENRE_IDS[g] for g in genres if g in GENRE_IDS
        ]

        preferences = {
            "선호 장르": genres,
            "보고 싶은 요소": features,
            "피하고 싶은 요소": avoid,
            "관람 상황": context,
            "추가 요청": extra
        }

        if not TMDB_API_KEY:
            error = "TMDB API 키를 찾지 못했습니다."

        elif not OPENAI_API_KEY:
            error = "OpenAI API 키를 찾지 못했습니다."

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
                        "release_date.lte": datetime.now().strftime("%Y-%m-%d"),
                        "page": 1
                    },
                    timeout=15
                )

                response.raise_for_status()
                movies = response.json().get("results", [])

                # 개봉일이 없거나 미래인 영화 제외
                today = datetime.now().strftime("%Y-%m-%d")

                movies = [
                    movie for movie in movies
                    if movie.get("release_date")
                    and movie["release_date"] <= today
                ]

                # TMDB에서 가져온 영화가 없는 경우
                if not movies:
                    error = "조건에 맞는 개봉 영화를 찾지 못했어요. 장르를 변경해 다시 시도해 주세요."

                else:
                    for movie in movies:
                        movie["genre_names"] = [
                            name for name, genre_id in GENRE_IDS.items()
                            if genre_id in movie.get("genre_ids", [])
                        ]

                    # AI가 사용자 취향에 맞는 영화를 선별
                    movies = recommend_movies(movies, preferences)

                    if not movies:
                        error = "입력한 취향에 맞는 영화를 찾지 못했어요. 장르나 추가 요청을 변경해 다시 시도해 주세요."

                    else:
                        recommendation_id = str(uuid.uuid4())
                        save_recommendation(
                            recommendation_id,
                            preferences,
                            movies
                        )

            except requests.exceptions.RequestException as e:
                print("TMDB 오류:", e)
                error = "TMDB 연결에 실패했습니다."

            except Exception as e:
                print("AI 추천 오류:", e)
                error = "AI 추천에 실패했습니다. API 키와 사용량을 확인해주세요."

    return render_template(
        "index.html",
        submitted=(request.method == "POST"),
        preferences=preferences,
        movies=movies,
        error=error,
        recommendation_id=recommendation_id
    )


if __name__ == "__main__":
    app.run(debug=True)
