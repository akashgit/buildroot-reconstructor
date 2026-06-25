FROM eclipse-temurin:8-jdk
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /build/target
WORKDIR /build
RUN curl -fsSL -o target/bcprov-jdk15on-1.70.jar https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk15on/1.70/bcprov-jdk15on-1.70.jar
