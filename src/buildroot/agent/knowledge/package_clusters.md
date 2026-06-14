# Package Clusters

## By Build Characteristics

### Single-Module Standard
- `org.apache.commons:commons-lang3` — baseline, solves in 1 iteration
- Simple `mvn package -DskipTests` builds

### Multi-Module Reactor
- Projects with parent POM + child modules
- Require reactor-aware build ordering

### Spring Ecosystem
- `org.springframework.*` packages
- Spring Boot plugin, dependency management BOMs

### Metrics / Observability
- `io.micrometer:micrometer-core` — typically JDK 11+
- Often use shade/shadow plugins
