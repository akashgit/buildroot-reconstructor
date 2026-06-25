FROM eclipse-temurin:8-jdk

ENV SOURCE_DATE_EPOCH=0
ENV TZ=UTC

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch 'jackson-core-2.15.3' 'https://github.com/FasterXML/jackson-core.git' /build
WORKDIR /build

# Use the project's own maven wrapper - it downloads Maven 3.9.3
RUN chmod +x ./mvnw && \
    ./mvnw -B -ntp package -DskipTests -Dgpg.skip=true && \
    rm -rf target/modules target/*-sources.jar target/*-javadoc.jar