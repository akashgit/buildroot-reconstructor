FROM eclipse-temurin:17-jdk AS builder
RUN echo build
FROM scratch
COPY --from=builder /app /app
