# Templates for Teyra AI Assistant

TEMPLATES = {
    'adr': {
        'name': 'Architecture Decision Record',
        'content': '''# ADR-{number}: {Title}

## Status
Proposed | Accepted | Deprecated | Superseded

## Context
What is the issue that we're seeing that is motivating this decision or change?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or more difficult to do because of this change?

## Alternatives Considered
What other options did we consider?

## References
Links to relevant documentation, discussions, or other ADRs.'''
    },
    'hld': {
        'name': 'High-Level Design Template',
        'content': '''# High-Level Design: {System Name}

## Overview
Brief description of the system and its purpose.

## Goals and Requirements
- Functional requirements
- Non-functional requirements
- Constraints

## Architecture Overview

```mermaid
graph TB
    A[Client] --> B[API Gateway]
    B --> C[Service Layer]
    C --> D[Data Layer]
```

## System Components
### Component 1
- Purpose
- Responsibilities
- Interfaces

## Data Flow
Describe how data flows through the system.

## Security Considerations
Authentication, authorization, data protection.

## Scalability and Performance
Expected load, scaling strategies.

## Monitoring and Observability
Logging, metrics, alerting strategies.'''
    },
    'code_review': {
        'name': 'Code Review Checklist',
        'content': '''# Code Review Checklist

## Functionality
- [ ] Code does what it's supposed to do
- [ ] Edge cases are handled
- [ ] Error handling is appropriate

## Code Quality
- [ ] Code follows established conventions
- [ ] Variables and functions are well-named
- [ ] Code is DRY (Don't Repeat Yourself)
- [ ] Functions are small and focused

## Security
- [ ] No hardcoded secrets or credentials
- [ ] Input validation is implemented
- [ ] SQL injection prevention
- [ ] XSS prevention (for web apps)

## Performance
- [ ] No obvious performance bottlenecks
- [ ] Database queries are optimized
- [ ] Appropriate data structures used

## Testing
- [ ] Unit tests cover new functionality
- [ ] Tests are meaningful and not just for coverage
- [ ] Integration tests where appropriate

## Documentation
- [ ] Code is self-documenting
- [ ] Complex logic is commented
- [ ] API documentation updated if needed'''
    }
}
