# Anti-Bot Service — Implementation Plan

## Overview

A NestJS/TypeORM/PostgreSQL service that ingests OnlyFans subscriber data per tracking link, persists it, and returns a risk category (`low | medium | high`) per tracking link.

Risk is computed in TypeScript by `CategorizationService` and stored in a dedicated `tracking_link_categories` table. It is refreshed synchronously after every upsert. A background job also periodically picks up any tracking links marked as unprocessed in case a synchronous refresh failed.

---

## File Structure

```
of_anti_bot/
├── src/
│   ├── app.module.ts
│   ├── main.ts                               # bootstrap, global ValidationPipe
│   │
│   ├── database/
│   │   └── database.module.ts                # TypeORM async config from ConfigModule
│   │
│   ├── tracking-link/
│   │   ├── tracking-link.module.ts           # imports ScheduleModule.forFeature()
│   │   ├── tracking-link.controller.ts       # POST /tracking-links, GET /tracking-links
│   │   ├── tracking-link.job.ts              # @Cron job: processes unprocessed links
│   │   │
│   │   ├── dto/
│   │   │   ├── upsert-tracking-link.dto.ts   # inbound: { trackingLinkId, subscriptions }
│   │   │   ├── onlyfans-user.dto.ts          # nested: id, username, registrationDate, subscriptionDate
│   │   │   └── tracking-link-risk.dto.ts     # outbound: { trackingLinkId, risk, visits }
│   │   │
│   │   ├── entities/
│   │   │   ├── tracking-link.entity.ts       # id, isProcessed, updatedAt
│   │   │   ├── subscriber.entity.ts          # inner user representation, FK → TrackingLink
│   │   │   └── tracking-link-category.entity.ts  # cache: trackingLinkId, risk, visits, updatedAt
│   │   │
│   │   ├── mappers/
│   │   │   ├── onlyfans-user.mapper.ts       # OnlyfansUserDto → Subscriber (pure function)
│   │   │   └── tracking-link-category.mapper.ts  # TrackingLinkCategory → TrackingLinkRiskDto
│   │   │
│   │   ├── repositories/
│   │   │   └── tracking-link.repository.ts   # all DB operations for this module
│   │   │
│   │   └── categorization/
│   │       ├── categorization.service.interface.ts  # ICategorizationService
│   │       └── categorization.service.ts            # mock implementation
│   │
├── test/
│   └── app.e2e-spec.ts
│
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── package.json
└── tsconfig.json
```

---

## Entities

### `TrackingLink` (`tracking_links`)

| Column        | Type        | Notes                                          |
|---------------|-------------|------------------------------------------------|
| `id`          | `varchar`   | PK, equals `trackingLinkId`                    |
| `isProcessed` | `boolean`   | `false` on upsert, `true` after job processes  |
| `updatedAt`   | `timestamp` | auto-updated on upsert                         |

### `Subscriber` (`subscribers`)

Inner representation — external field names appear only in the mapper.

| Column           | Type        | Notes                             |
|------------------|-------------|-----------------------------------|
| `id`             | `serial`    | PK                                |
| `externalId`     | `varchar`   | maps from `OnlyfansUser.id`       |
| `username`       | `varchar`   | maps from `OnlyfansUser.username` |
| `registeredAt`   | `timestamp` | maps from `registrationDate`      |
| `subscribedAt`   | `timestamp` | maps from `subscriptionDate`      |
| `trackingLinkId` | `varchar`   | FK → `TrackingLink.id`            |

Unique constraint: `(externalId, trackingLinkId)`.

### `TrackingLinkCategory` (`tracking_link_categories`)

Precomputed cache — populated on upsert and back-filled by the job.

| Column           | Type        | Notes                         |
|------------------|-------------|-------------------------------|
| `trackingLinkId` | `varchar`   | PK, FK → `TrackingLink.id`    |
| `risk`           | `enum`      | `'low' \| 'medium' \| 'high'` |
| `visits`         | `integer`   | total subscriber count        |
| `updatedAt`      | `timestamp` | set on each refresh           |

---

## DTOs

### `OnlyfansUserDto`
```ts
{ id: string; username: string; registrationDate: string; subscriptionDate: string }
```
Dates as ISO strings, validated with `@IsDateString()`.

### `UpsertTrackingLinkDto`
```ts
{ trackingLinkId: string; subscriptions: OnlyfansUserDto[] }
```

### `TrackingLinkRiskDto` (response)
```ts
{ trackingLinkId: string; risk: 'low' | 'medium' | 'high'; visits: number }
```

---

## Mapper: `onlyfans-user.mapper.ts`

Pure function — no DI, no side effects. The **only** place where external field names are referenced.

```ts
function toSubscriberEntity(dto: OnlyfansUserDto): Partial<Subscriber> {
  return {
    externalId:   dto.id,
    username:     dto.username,
    registeredAt: new Date(dto.registrationDate),
    subscribedAt: new Date(dto.subscriptionDate),
  };
}
```

---

## Mapper: `tracking-link-category.mapper.ts`

Pure function — maps the internal cache entity to the outbound response DTO. Used in `findAllRisks()`.

```ts
function toRiskDto(entity: TrackingLinkCategory): TrackingLinkRiskDto {
  return {
    trackingLinkId: entity.trackingLinkId,
    risk:           entity.risk,
    visits:         entity.visits,
  };
}
```

---

## CategorizationService — Interface & Mock

```ts
// categorization.service.interface.ts
export interface ICategorizationService {
  /** Scores a single subscriber based on account characteristics. */
  scoreSubscriber(subscriber: Subscriber): 'low' | 'medium' | 'high';

  /** Aggregates per-subscriber scores into a tracking-link-level risk. */
  aggregateRisk(scores: Array<'low' | 'medium' | 'high'>): 'low' | 'medium' | 'high';
}

// categorization.service.ts — mock (real logic TBD)
@Injectable()
export class CategorizationService implements ICategorizationService {
  scoreSubscriber(_subscriber: Subscriber): 'low' | 'medium' | 'high' {
    return 'low';
  }
  aggregateRisk(_scores: Array<'low' | 'medium' | 'high'>): 'low' | 'medium' | 'high' {
    return 'low';
  }
}
```

**Planned real scoring logic** (to implement when mock is replaced):

*Per-subscriber signals:*
| Signal                                                | Result risk |
|-------------------------------------------------------|-------------|
| Account age at subscription < 3 days                  | `high`      |
| Account age at subscription < 14 days                 | `medium`    |
| `subscribedAt − registeredAt` < 1 hour               | `high`      |
| Username matches bot pattern (high digit ratio, etc.) | +1 level    |

*Aggregation thresholds:*
| Condition                                   | Link risk |
|---------------------------------------------|-----------|
| ≥ 30% of subscribers scored `high`          | `high`    |
| ≥ 15% `high` OR ≥ 40% `medium`             | `medium`  |
| otherwise                                   | `low`     |

All thresholds extracted to `categorization.constants.ts` when implemented.

---

## Repository: `TrackingLinkRepository`

### `upsert(dto: UpsertTrackingLinkDto): Promise<void>`

1. Open a `DataSource` transaction.
2. Upsert `TrackingLink` with `isProcessed = false` (insert or update, always resets the flag).
3. Delete all `Subscriber` rows for `trackingLinkId`.
4. Map `dto.subscriptions → Subscriber[]` via mapper, attach `trackingLinkId`.
5. Bulk-insert new subscribers.
6. Commit transaction.
7. **After commit** — call `this.refreshCategory(trackingLinkId)`.
   If this throws, log the error but do **not** fail the HTTP request — the job will recover it.

### `refreshCategory(trackingLinkId: string): Promise<void>`

1. Load all `Subscriber` rows for the link.
2. Score each via `categorizationService.scoreSubscriber()`.
3. Aggregate via `categorizationService.aggregateRisk()`.
4. Upsert `TrackingLinkCategory`: `{ trackingLinkId, risk, visits: count, updatedAt: now }`.
5. Set `TrackingLink.isProcessed = true`.

### `findUnprocessed(): Promise<TrackingLink[]>`

```ts
repository.findBy({ isProcessed: false })
```

### `findAllRisks(): Promise<TrackingLinkRiskDto[]>`

`SELECT` from `tracking_link_categories`. Links not yet categorized are excluded until processed (or can default to `low / 0` via a LEFT JOIN if needed).

---

## Background Job: `TrackingLinkJob`

```ts
@Injectable()
export class TrackingLinkJob {
  constructor(private readonly repository: TrackingLinkRepository) {}

  @Cron(CronExpression.EVERY_MINUTE)
  async processUnprocessed(): Promise<void> {
    const links = await this.repository.findUnprocessed();
    for (const link of links) {
      await this.repository.refreshCategory(link.id);
    }
  }
}
```

- Runs every minute (configurable via env `CATEGORY_JOB_INTERVAL`).
- Finds all `TrackingLink` rows where `isProcessed = false`.
- Calls `refreshCategory()` for each, which sets `isProcessed = true` on success.
- Errors per link are logged and skipped; the link remains `isProcessed = false` and is retried on the next tick.

---

## Data Flow

```
POST /tracking-links
  └─ Controller
       └─ TrackingLinkRepository.upsert()
            ├─ [transaction] upsert TrackingLink { isProcessed: false }
            ├─ [transaction] delete old Subscribers
            ├─ [transaction] insert new Subscribers via mapper
            └─ refreshCategory()  ← errors swallowed + logged
                 ├─ load Subscribers
                 ├─ CategorizationService.scoreSubscriber() × N
                 ├─ CategorizationService.aggregateRisk()
                 ├─ upsert TrackingLinkCategory { risk, visits }
                 └─ set TrackingLink.isProcessed = true

Background job (every minute)
  └─ TrackingLinkJob.processUnprocessed()
       └─ findUnprocessed()  →  WHERE isProcessed = false
            └─ refreshCategory(id) × M  ← same logic as above

GET /tracking-links
  └─ Controller
       └─ TrackingLinkRepository.findAllRisks()
            └─ SELECT from tracking_link_categories  ← no computation
```

---

## Database Module

```ts
TypeOrmModule.forRootAsync({
  imports: [ConfigModule],
  useFactory: (config: ConfigService) => ({
    type: 'postgres',
    host:     config.get('DB_HOST'),
    port:     config.get<number>('DB_PORT'),
    username: config.get('DB_USER'),
    password: config.get('DB_PASSWORD'),
    database: config.get('DB_NAME'),
    entities: [TrackingLink, Subscriber, TrackingLinkCategory],
    synchronize: config.get('NODE_ENV') !== 'production',
  }),
  inject: [ConfigService],
})
```

---

## Environment Variables (`.env.example`)

```env
NODE_ENV=development
PORT=3000

DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=anti_bot
```

---

## Docker Setup

### `Dockerfile` — multi-stage

```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile
COPY . .
RUN yarn build

FROM node:22-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
CMD ["node", "dist/main"]
```

### `docker-compose.yml`

```yaml
services:
  api:
    build: .
    ports:
      - "3000:3000"
    environment:
      NODE_ENV: production
      PORT: 3000
      DB_HOST: postgres
      DB_PORT: 5432
      DB_USER: postgres
      DB_PASSWORD: postgres
      DB_NAME: anti_bot
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: anti_bot
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

---

## Dependencies to Add

```bash
yarn add @nestjs/typeorm typeorm pg @nestjs/config @nestjs/schedule class-validator class-transformer
```

---

## Run Modes

| Mode        | Command                     |
|-------------|-----------------------------|
| Development | `yarn start:dev`            |
| Production  | `yarn start:prod`           |
| Docker      | `docker-compose up --build` |

---

## Key Design Decisions

1. **`TrackingLinkCategory` cache table** — risk is computed in TypeScript and stored. GET reads precomputed rows; no per-request scoring.

2. **`isProcessed` flag on `TrackingLink`** — set to `false` on every upsert, set to `true` by `refreshCategory()`. The background job queries `WHERE isProcessed = false`, which is a simple indexed scan with no joins.

3. **Two-layer refresh** — synchronous refresh after each upsert (primary path) + a periodic job as fallback. Under normal operation the job finds no rows to process.

4. **Encapsulated mapping** — `onlyfans-user.mapper.ts` is the sole boundary between external field names and internal entity fields.

5. **Full replace on upsert** — deleting all subscribers before re-inserting is simpler and correct per spec ("rewriting preexisting subscriptions").

6. **`CategorizationService` as interface + mock** — seam for future replacement without changing any consumer code.

7. **No `TrackingLinkService`** — the repository owns all DB + categorization orchestration.

8. **`synchronize: true` in dev only** — schema auto-managed in dev; production would require explicit migrations.
