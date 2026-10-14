# Docker Notes – Tasks 1 to 7

Hands-on Docker learning, done in WSL (Ubuntu) with Docker Engine + BuildKit (buildx).

---

## Task 1 – Changes inside a container are temporary

- An **image** is read-only. When a container starts, Docker adds a thin **writable layer** on top.
- Any change made inside a running container (e.g. editing a file with `docker exec`) goes into that writable layer.
- `docker rm` deletes the writable layer, so the change is lost. A new container starts fresh from the image.
- Rule: **never "fix" things inside a running container**. Change the image or config and redeploy. (Same in Kubernetes: changes inside a pod are lost when it restarts.)

**`docker run` vs `docker exec`**
- `docker run` → **creates a new container** from an image.
- `docker exec` → runs a command **inside an already running** container.
- `-it` = `-i` (keep input open) + `-t` (give a terminal).

**Port mapping**
```
-p 8080:80
   │    └── port INSIDE the container (where the app listens)
   └─────── port on MY MACHINE (what I open in the browser)
```
- Many containers can use the same port inside (e.g. 80), as long as each uses a different **host** port.
- Two containers can't share the same host port → `port is already allocated`.

---

## Task 2 – Bind mounts

```bash
docker run -d -p 8080:80 --name web -v ~/devops-learning/site:/usr/share/nginx/html nginx
```
- Links a **folder on my machine** to a folder inside the container.
- Edits on my machine show up immediately in the container (no restart).
- Data survives container deletion because it never lived inside the container.
- Left side = my machine, right side = container (same order as `-p`).
- Used for local development, **not** for real deployments.

---

## Task 3 – Named volumes

```bash
docker volume create mydata
docker run --rm -v mydata:/data alpine sh -c "echo 'saved' > /data/note.txt"
docker run --rm -v mydata:/backup alpine cat /backup/note.txt   # same file, different path
docker volume rm mydata
```
- A volume is storage **managed by Docker**, independent of any container (like a USB drive).
- `-v mydata:/data` = plug the volume in at `/data` for this container's lifetime.
- On the host it's stored at `/var/lib/docker/volumes/mydata/_data/`. `_data` is the volume's root, and it's what appears at the container path. The container never sees `_data`.
- `docker volume inspect` shows metadata (Mountpoint), **not** the contents.
- How Docker decides: plain name (`mydata`) → named volume; absolute path (`/...`, `~/...`) → bind mount. `mydata/_data` is invalid.
- Gotcha: a typo in a volume name silently creates a **new empty volume** → looks like data loss.
- Databases, Kafka, file uploads (stateful) need volumes; web apps (stateless) usually don't. Kubernetes equivalent: **PersistentVolumes** (EBS on EKS).
- `--rm` → automatically remove the container when it exits.

**Shell lessons (`sh -c`)**
- Whatever comes after the image name is the command the container runs (replaces `CMD`).
- `sh -c "..."` → run the string as a shell command inside the container.
- `>` redirection is a **shell feature**. Without `sh -c "..."`, my WSL shell handles `>` and writes on my machine.
- The first word of an error shows **who** failed: `-bash:` (my shell), `docker:` (Docker), or the app itself.

---

## Task 4 – Building my own image

**Dockerfile**
```dockerfile
FROM python:3.12-slim                                # base image: Linux + Python
WORKDIR /app                                          # create /app in the image and cd into it
COPY requirements.txt .                               # copy from my machine into /app
RUN pip install --no-cache-dir -r requirements.txt   # runs at BUILD time, saved as a layer
COPY . .                                              # copy the rest of my code into /app
EXPOSE 5000                                           # documentation only, opens nothing
CMD ["python", "app.py"]                              # runs at RUN time, becomes PID 1
```
- File name is exactly `Dockerfile` (capital D, no extension). Other names need `-f`.
- **`RUN` shapes the image, `CMD` starts the container.**
- `EXPOSE` doesn't publish a port; `-p` does.
- The image **contains copies** of my files. Nothing is read from my PC at run time. Changing code means rebuild → push → redeploy.

**Build and run**
```bash
docker build -t myapp:v1 .     # -t = name:tag, . = build context (files Docker can COPY)
docker run -d -p 5000:5000 --name myapp myapp:v1
curl localhost:5000
```
- `Hello from <id>` = container hostname = short container ID (useful to see which pod answered in Kubernetes).
- `host="0.0.0.0"` in the app is required; `127.0.0.1` would make it unreachable from outside the container.

**Build once, configure per environment**
```bash
docker run -d -p 5001:5000 -e APP_ENV=staging --name myapp2 myapp:v1
```
- Same image, different config via environment variables. In Kubernetes → ConfigMaps/Secrets; in Helm → `values-dev.yaml`, `values-prod.yaml`.
- A failed `docker run` can leave a half-created container ("Created" state) → name conflict on retry. Check `docker ps -a`.

**Mistakes I made (and learned from)**
- `docker bulid` → typo caused a misleading `-t` error.
- Missing `.` → `'docker build' requires 1 argument`.
- Wrong folder → Dockerfile not found.
- `docker stop myapp:v1` → `No such container` (that's an image name, stop needs a container name/ID).

---

## Task 5 – Layer caching

- Each Dockerfile instruction = one layer. Docker reuses (CACHED) layers that haven't changed.
- `COPY` → cache checks the **contents** of copied files.
- `RUN` → cache checks only the **command text** and the **layer below it**. Docker doesn't know which files pip reads.
- **Once one layer changes, every layer after it rebuilds.**
- Good order: copy `requirements.txt` → install → copy code. Bad order: copy everything → install.

| Build (only app.py changed) | pip install | Total |
|---|---|---|
| Good order | CACHED | 0.4s |
| Bad order | ran again (4.8s) | 5.9s |

- Real impact: 30 pushes/day × 3 min install = **90 min/day** wasted with bad order.
- Switching from the legacy builder to BuildKit lost the cache (separate caches).
- In CI (GitHub Actions), runners start fresh → cache must be saved/restored explicitly (`cache-from` / `cache-to`).

---

## Task 6 – Registries (Docker Hub, ECR)

```bash
docker login
docker tag myapp:v2.1 dineshtankalaedu/myapp:v2.1
docker push dineshtankalaedu/myapp:v2.1
docker run -d -p 5002:5000 --name fromhub dineshtankalaedu/myapp:v2.1
```
- `docker tag` **only adds another name** to the same image locally (same IMAGE ID). Nothing is uploaded.
- `docker push` uploads. Tag = label, push = upload.
- `docker rmi` on one of several tags only **untags**; layers are deleted when the last tag is removed.
- Image name format: `registry/namespace/repository:tag`. No registry → `docker.io`. No namespace → official images (`docker.io/library/...`).
- ECR format: `<account-id>.dkr.ecr.<region>.amazonaws.com/myapp:tag`. The name tells Docker where to push.
- Docker checks locally first, then pulls (`Unable to find image ... locally` → `Pulling from ...`).
- Tags are just labels; they don't guarantee content. Best practice: tag with Git commit ID, enable **tag immutability** in ECR.
- Pushing an image whose layers already exist → `Layer already exists` (fast).

**Pull errors**
- `pull access denied ... repository does not exist` → wrong/incomplete image name.
- `manifest ... not found: manifest unknown` → tag doesn't exist in the registry.
- Kubernetes equivalent: `ErrImagePull` → `ImagePullBackOff`.

---

## Task 7 – Troubleshooting broken containers

**Standard flow:** `docker ps` → `docker ps -a` (status + exit code) → `docker logs <name>` → `docker inspect <name> --format '{{.State.ExitCode}}'`

| Case | Symptom | Root cause | Fix |
|---|---|---|---|
| Broken 1: `python wrong.py` | Exited (2), logs: can't open file | Command points to a file that doesn't exist | Correct the command / check COPY and `.dockerignore` |
| Broken 2: `-p 5003:8080` | Running, but curl fails, no requests in logs | App listens on 5000, traffic sent to 8080 | `-p 5003:5000` |
| Broken 3: `sleep 5` | Exited (0), empty logs | **Not broken**: command finished successfully | Nothing (in K8s, one-off tasks → Jobs) |

**Key lessons**
- "Running" doesn't mean "working". Docker doesn't check the app listens on the mapped port.
- The **app decides its listening port** (in code/config). `-p` only forwards. Make it configurable: `port = int(os.getenv("PORT", 5000))`.
- No request lines in app logs → problem is the **network path**, not the app.
- K8s equivalents: Broken 1 → `CrashLoopBackOff` (`kubectl logs --previous`); Broken 2 → Service `targetPort` mismatch → 502/503; Broken 3 in a Deployment → `CrashLoopBackOff` with reason `Completed`.
- Without `-d`, the container runs in the foreground; Ctrl+C stops it. Use `docker logs -f` to follow logs instead.

**Exit codes**

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General app error |
| 2 | Misuse / file not found |
| 125 | Docker failed to run the container |
| 126 | Command not executable |
| 127 | Command not found |
| 137 | Killed (SIGKILL), often OOMKilled |
| 143 | Stopped gracefully (SIGTERM) |
| 255 | Abnormal exit (e.g. Docker/WSL shut down) |

**HTTP status codes**

| Code | Meaning | Usually points to |
|---|---|---|
| 200 | OK | Worked |
| 404 | Not found | Wrong URL/path, Ingress path |
| 500 | Server error | Bug/crash in the app |
| 502 | Bad gateway | LB reached nothing valid (port mismatch, app down) |
| 503 | Unavailable | No healthy backends (readiness failing) |
| 504 | Timeout | App too slow |

4xx = request was wrong, 5xx = server side failed.

---

## Command cheat sheet

```bash
docker ps / docker ps -a              # running / all containers
docker logs [-f] [--tail N] <name>    # logs (follow, last N)
docker exec -it <name> sh             # shell into running container
docker inspect <name> --format '{{.State.ExitCode}}'
docker stats --no-stream / docker top <name>
docker build -t name:tag .
docker images / docker history <image>
docker tag <src> <dest> / docker push <image> / docker pull <image>
docker rm -f <name> / docker rmi <image>
docker volume create|ls|inspect|rm <name>
docker system df                      # disk usage
```
Avoid `docker container prune` when other projects have stopped containers I still need.
