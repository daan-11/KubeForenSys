# Neo4J Kubernetes Lateral Movement Detection - Implementation Checklist

## Pre-Implementation Setup
- [ ] Verify Neo4J database contains all required node types (Pod, Service, ServiceAccount, Namespace, NetworkPolicy, etc.)
- [ ] Confirm edge types match your graph (SELECTS, AUTHENTICATED_AS, GRANTED, ALLOWS, RUNS_ON, IN_NAMESPACE, ENDPOINT_OF, OWNS)
- [ ] Set up development environment with Python 3.8+

## Phase 1: Neo4J Integration & Baseline Collection (3 hours)

### 1.1 Setup Neo4J Connection (30 min)
- [ ] `pip install neo4j pandas networkx scipy numpy`
- [ ] Create `neo4j_connector.py` with connection class
- [ ] Test basic connectivity and node counting queries
- [ ] Implement query helper functions

**Test Query to Validate Setup:**
```cypher
MATCH (n) RETURN labels(n) as node_types, count(n) as count
```

### 1.2 Create Baseline Data Collector (1 hour)
- [ ] Implement metrics collection queries in `baseline_tracker.py`
- [ ] Create pandas DataFrame for rolling 7-day storage
- [ ] Add persistent storage (pickle backup every hour)
- [ ] Test baseline collection on current graph

**Key Metrics to Collect:**
- Pod degree (in/out connections per pod)
- Cross-namespace edge count per hour
- Service account usage frequency
- New edge formation rate

### 1.3 Path Analysis Infrastructure (1 hour)
- [ ] Implement path detection queries in `path_detector.py`
- [ ] Create path scoring algorithm (namespace crossing +2, privilege escalation +3)
- [ ] Test shortest path queries between random pod pairs
- [ ] Validate performance on your graph size

### 1.4 Centrality Calculation (30 min)
- [ ] Create Neo4J → NetworkX conversion function
- [ ] Implement centrality calculation in `centrality_detector.py`
- [ ] Set up centrality time series storage
- [ ] Test centrality spike detection logic

**Deliverable Check:**
- [ ] Can connect to Neo4J and query your graph
- [ ] Baseline metrics updating every 60 seconds
- [ ] Path queries return expected results
- [ ] Centrality calculations complete in <5 seconds

## Phase 2: Core Detection Algorithms (7 hours)

### 2.1 Path-Based Lateral Movement Detection (3 hours)
- [ ] Implement cross-namespace access detection
- [ ] Create privilege escalation chain detector 
- [ ] Add service account hopping detection
- [ ] Build path anomaly scoring system
- [ ] Test with known attack scenarios

**Critical Queries to Implement:**
```cypher
// Cross-namespace detection
MATCH path = (source_pod:Pod)-[:IN_NAMESPACE]->(ns1:Namespace),
             (target_pod:Pod)-[:IN_NAMESPACE]->(ns2:Namespace),
             shortestPath((source_pod)-[*1..4]-(target_pod))
WHERE ns1.name <> ns2.name AND source_pod <> target_pod
RETURN path, ns1.name, ns2.name

// Privilege escalation detection  
MATCH path=(pod:Pod)-[:AUTHENTICATED_AS]->(sa:ServiceAccount)-[:GRANTED*1..3]->(binding)
WHERE (binding:RoleBinding OR binding:ClusterRoleBinding)
RETURN path, pod.name, sa.name, binding.name
```

### 2.2 Statistical Baseline Anomaly Detection (2 hours)
- [ ] Implement z-score calculation for all tracked metrics
- [ ] Create anomaly detection with threshold = 3.0 standard deviations
- [ ] Add different thresholds for different resource types
- [ ] Test anomaly detection with artificial spikes

**Algorithm Implementation:**
```python
def detect_statistical_anomalies(current_metrics, baseline):
    alerts = []
    for metric, value in current_metrics.items():
        z_score = (value - baseline[metric]['mean']) / baseline[metric]['std']
        if abs(z_score) > 3.0:
            alerts.append(create_anomaly_alert(metric, value, z_score))
    return alerts
```

### 2.3 Centrality Spike Detection (1 hour)
- [ ] Compare current vs 24-hour rolling average centrality
- [ ] Flag centrality increases > 2 standard deviations
- [ ] Focus on betweenness centrality for pivot detection
- [ ] Test with artificial graph topology changes

### 2.4 Alert Scoring & Ranking (1 hour)  
- [ ] Implement combined scoring formula: `0.5*path + 0.3*statistical + 0.2*centrality`
- [ ] Add severity multipliers for different attack types
- [ ] Create alert deduplication logic
- [ ] Test alert ranking with mixed scenarios

**Deliverable Check:**
- [ ] Path detector flags cross-namespace access
- [ ] Statistical detector catches degree anomalies
- [ ] Centrality detector identifies sudden pivots
- [ ] Alert manager produces ranked, deduplicated alerts

## Phase 3: Alerting & Visualization (4 hours)

### 3.1 Alert Structure Design (1 hour)
- [ ] Define JSON alert schema with required fields
- [ ] Create alert categories (LATERAL_MOVEMENT, PRIVILEGE_ESCALATION, POLICY_VIOLATION)
- [ ] Add evidence and recommendation fields
- [ ] Test alert serialization/deserialization

**Alert Schema:**
```json
{
  "timestamp": "2025-10-19T14:00:00Z",
  "severity": "HIGH", 
  "type": "LATERAL_MOVEMENT",
  "source_pod": "compromised-pod-123",
  "target_pod": "sensitive-app-456", 
  "attack_path": "Pod(ns1) → ServiceAccount → Pod(ns2)",
  "evidence": {...},
  "recommendations": ["Revoke service account", "Enforce network policy"]
}
```

### 3.2 Neo4J Path Visualization (1.5 hours)
- [ ] Query Neo4J for evidence subgraph around each alert
- [ ] Convert graph paths to readable ASCII format
- [ ] Add node attributes (labels, namespace, permissions)
- [ ] Create visual path representation

**Path Visualization Example:**
```
LATERAL MOVEMENT DETECTED:
compromised-pod[default] 
  ↓ AUTHENTICATED_AS
service-account-x[default]
  ↓ GRANTED  
cluster-role-binding[cluster-wide]
  ↓ ACCESS_TO
sensitive-pod[prod-namespace]
```

### 3.3 Output & Integration (1 hour)
- [ ] Implement CLI output with color coding (red=high, yellow=medium)
- [ ] Add JSON file output for SIEM integration
- [ ] Optional: webhook POST to external system
- [ ] Set up log rotation and retention

### 3.4 Alert Filtering & Tuning (30 min)
- [ ] Add severity threshold filtering
- [ ] Implement whitelist for known-good paths
- [ ] Create rate limiting (max 10 alerts/minute)
- [ ] Add maintenance mode functionality

**Deliverable Check:**
- [ ] Alerts contain all required evidence
- [ ] Path visualization is clear and actionable  
- [ ] Multiple output formats working
- [ ] Rate limiting prevents alert floods

## Phase 4: Main Controller & Integration (3 hours)

### 4.1 Main Detection Loop (1 hour)
- [ ] Create `main.py` with orchestration logic
- [ ] Implement 60-second detection cycle
- [ ] Add exception handling for continued operation
- [ ] Test full pipeline end-to-end

**Main Loop Structure:**
```python
while True:
    try:
        # Collect current metrics
        current_metrics = baseline_tracker.collect_metrics()
        
        # Run all detectors
        path_alerts = path_detector.detect_anomalies()
        stat_alerts = baseline_tracker.detect_anomalies()
        cent_alerts = centrality_detector.detect_anomalies()
        
        # Score and output alerts
        alert_manager.process_alerts(path_alerts + stat_alerts + cent_alerts)
        
        time.sleep(60)
    except Exception as e:
        logger.error(f"Detection cycle failed: {e}")
        time.sleep(60)
```

### 4.2 Configuration Management (30 min)
- [ ] Create `config.yaml` with all tunable parameters
- [ ] Add environment variable override support
- [ ] Implement configuration validation
- [ ] Document all configuration options

**Key Configuration Parameters:**
```yaml
neo4j:
  uri: "bolt://localhost:7687"
  username: "neo4j"
  password: "password"

detection:
  snapshot_interval: 60
  baseline_window_days: 7
  z_score_threshold: 3.0
  max_path_length: 4
  centrality_spike_threshold: 2.0

alerting:
  severity_threshold: "MEDIUM"
  rate_limit_per_minute: 10
  output_formats: ["cli", "json"]
```

### 4.3 Logging & Monitoring (1 hour)
- [ ] Add structured JSON logging throughout
- [ ] Log performance metrics (query times, detection latency)
- [ ] Create health check functionality  
- [ ] Add startup validation checks

### 4.4 Error Handling & Resilience (30 min)
- [ ] Handle Neo4J connection failures gracefully
- [ ] Continue operation if one detector fails
- [ ] Implement retry logic for transient failures
- [ ] Add graceful shutdown on SIGTERM

**Deliverable Check:**
- [ ] Complete system runs continuously without crashes
- [ ] Configuration easily tunable without code changes
- [ ] Comprehensive logging and health monitoring
- [ ] Resilient to various failure modes

## Phase 5: Testing & Production Readiness (3 hours)

### 5.1 Functional Testing (1.5 hours)
- [ ] Create test pods with suspicious cross-namespace access
- [ ] Test privilege escalation scenario (pod → SA → admin role)
- [ ] Verify service account hopping detection
- [ ] Confirm alert generation and formatting

**Test Scenarios to Create:**
1. Deploy pod in `test-ns` that accesses service in `prod-ns`
2. Create service account with excessive cluster permissions
3. Deploy pod that connects to many other pods (C2 simulation)
4. Create rapid pod deployment/deletion (churn test)

### 5.2 Performance Testing (1 hour)
- [ ] Measure query performance with current graph size
- [ ] Test with high pod churn scenarios
- [ ] Monitor memory usage over 24-hour period
- [ ] Optimize slow queries using Neo4J EXPLAIN

**Performance Benchmarks to Hit:**
- Detection latency: <10 seconds
- Memory usage: <100MB steady state
- CPU usage: <5% average
- Query time: <1 second for path detection

### 5.3 Documentation & Deployment (30 min)
- [ ] Create comprehensive README.md
- [ ] Document all alert types and meanings
- [ ] Write deployment guide (systemd service, Docker)
- [ ] Document performance tuning recommendations

**Deliverable Check:**
- [ ] All test scenarios trigger appropriate alerts
- [ ] Performance meets requirements on your cluster size
- [ ] Complete documentation for deployment and operations
- [ ] System ready for production deployment

## Final Validation Checklist

- [ ] System detects cross-namespace lateral movement
- [ ] Privilege escalation through RBAC chains flagged
- [ ] Statistical anomalies in pod connectivity caught
- [ ] Centrality spikes (pivot points) identified
- [ ] Alerts contain actionable evidence and recommendations
- [ ] Performance acceptable for continuous operation
- [ ] Configuration externalized and documented
- [ ] Error handling prevents system crashes
- [ ] Complete deployment documentation available

## Quick Reference: Key Files and Their Purpose

- `main.py` - Orchestrates detection loop, entry point
- `neo4j_connector.py` - Database queries and connection management  
- `baseline_tracker.py` - Statistical baselines and anomaly detection
- `path_detector.py` - Graph path analysis for lateral movement
- `centrality_detector.py` - Network centrality spike detection
- `alert_manager.py` - Alert scoring, ranking, output formatting
- `config.yaml` - All configuration parameters
- `requirements.txt` - Python package dependencies

**Total Implementation Time: 20 hours over 2 weeks**
**Expected Result: Production-ready lateral movement detection system**