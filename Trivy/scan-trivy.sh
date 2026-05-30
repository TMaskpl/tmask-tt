# tmask-transporter-nginx-1

# 1) Skan obrazu -> raport JSON
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v trivy-cache:/root/.cache/ \
  -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  image --format json -o trivy.json nginx:1.25-alpine

# 2) Konwersja na format SonarQube (plugin = podkomenda `sonarqube`)
docker run --rm -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  sonarqube /work/trivy.json --filePath=Dockerfile > sonar-trivy-tmask-transporter-nginx-1.json

# tmask-transporter-web-1

# 1) Skan obrazu -> raport JSON
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v trivy-cache:/root/.cache/ \
  -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  image --format json -o trivy.json tmask-transporter-web:latest

# 2) Konwersja na format SonarQube (plugin = podkomenda `sonarqube`)
docker run --rm -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  sonarqube /work/trivy.json --filePath=Dockerfile > sonar-trivy-tmask-transporter-web-1.json

# tmask-transporter-beat-1

# 1) Skan obrazu -> raport JSON
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v trivy-cache:/root/.cache/ \
  -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  image --format json -o trivy.json tmask-transporter-beat:latest

# 2) Konwersja na format SonarQube (plugin = podkomenda `sonarqube`)
docker run --rm -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  sonarqube /work/trivy.json --filePath=Dockerfile > sonar-trivy-tmask-transporter-beat-1.json


# tmask-transporter-worker-1

# 1) Skan obrazu -> raport JSON
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v trivy-cache:/root/.cache/ \
  -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  image --format json -o trivy.json tmask-transporter-worker:latest

# 2) Konwersja na format SonarQube (plugin = podkomenda `sonarqube`)
docker run --rm -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  sonarqube /work/trivy.json --filePath=Dockerfile > sonar-trivy-tmask-transporter-worker-1.json


# tmask-transporter-postgres-1

# 1) Skan obrazu -> raport JSON
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v trivy-cache:/root/.cache/ \
  -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  image --format json -o trivy.json postgres:16-alpine

# 2) Konwersja na format SonarQube (plugin = podkomenda `sonarqube`)
docker run --rm -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  sonarqube /work/trivy.json --filePath=Dockerfile > sonar-trivy-tmask-transporter-postgres-1.json



  # tmask-transporter-redis-1

# 1) Skan obrazu -> raport JSON
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v trivy-cache:/root/.cache/ \
  -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  image --format json -o trivy.json redis:7-alpine

# 2) Konwersja na format SonarQube (plugin = podkomenda `sonarqube`)
docker run --rm -v "$PWD:/work" -w /work \
  trivy-sonar:0.70.0 \
  sonarqube /work/trivy.json --filePath=Dockerfile > sonar-trivy-tmask-transporter-redis-1.json