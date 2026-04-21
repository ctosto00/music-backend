# music-backend

Proxy Python+Flask che usa `yt-dlp` per risolvere YouTube video ID in URL audio
e farne relay. Girato su [Render](https://render.com) free tier.

## Endpoints

- `GET /` — hint d'uso
- `GET /health` — healthcheck
- `GET /audio?videoId=<id>` — streamma audio del video YouTube

## Deploy su Render

1. Fork/upload questa cartella su un repo GitHub
2. Su Render: **New Web Service** → connect al repo
3. Render legge `render.yaml` e fa tutto in automatico
4. Una volta deployato, URL tipo `https://music-backend-xxxx.onrender.com`

## Aggiornare yt-dlp

`yt-dlp` è senza versione in `requirements.txt` → ogni deploy prende l'ultima.
Per forzare un redeploy: click manuale su **Deploy latest commit** dal
dashboard Render, oppure `git commit --allow-empty -m "redeploy" && git push`.
