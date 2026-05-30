# Przypnij wersję zamiast :latest dla powtarzalnych buildów
FROM aquasec/trivy:0.70.0

# Bazowy obraz ma ENTRYPOINT ["trivy"], ale instrukcje RUN i tak
# uruchamiają się przez /bin/sh, więc apk i instalacja pluginu działają normalnie
RUN apk add --no-cache python3 \
    && trivy plugin install github.com/umax/trivy-plugin-sonarqube

# Przywracamy domyślny entrypoint (dziedziczony, ale zostawiam dla jasności)
ENTRYPOINT ["trivy"]