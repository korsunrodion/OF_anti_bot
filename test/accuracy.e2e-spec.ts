/* eslint-disable @typescript-eslint/no-unsafe-member-access */
/* eslint-disable @typescript-eslint/no-unsafe-assignment */
// Usage: npm run test:e2e -- --testPathPattern=accuracy
// Fetches rows from the external "subscriptions" DB, sends them through the HTTP API,
// waits for the job to classify, then compares results against original labels.

import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { Column, DataSource, Entity, PrimaryGeneratedColumn } from 'typeorm';
import { AppModule } from '../src/app.module';
import { TrackingLinkJob } from '../src/tracking-link/tracking-link.job';
import dotenv from 'dotenv';
dotenv.config();

@Entity('subscriptions')
class Subscription {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ name: 'user_id', type: 'bigint' })
  userId: string;

  @Column({ name: 'user_name' })
  userName: string;

  @Column({ name: 'subscribed_at' })
  subscribedAt: string;

  @Column({ name: 'risk_level' })
  riskLevel: string;

  @Column({ name: 'tracking_model_name', nullable: true })
  trackingModelName: string;
}

const PORT = parseInt(process.env.TEST_PORT ?? '3001', 10);
const BASE_URL = `http://localhost:${PORT}`;
const MODEL_COUNT = parseInt(process.env.MODEL_COUNT ?? '10', 10);
const SUBSCRIPTIONS_DB_URL =
  process.env.SUBSCRIPTIONS_DB_URL ??
  'postgres://postgres:17101996@localhost:5432/of_parser';
const AUTH_KEY = process.env.AUTH_KEY ?? '';

describe('Categorization accuracy (e2e)', () => {
  let app: INestApplication;
  let job: TrackingLinkJob;
  let appDataSource: DataSource;
  let extDataSource: DataSource;
  const insertedModelNames: string[] = [];

  beforeAll(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    app.useGlobalPipes(
      new ValidationPipe({ transform: true, whitelist: true }),
    );
    await app.listen(PORT);

    job = moduleFixture.get(TrackingLinkJob);
    appDataSource = moduleFixture.get(DataSource);

    extDataSource = new DataSource({
      type: 'postgres',
      url: SUBSCRIPTIONS_DB_URL,
      entities: [Subscription],
      synchronize: false,
      extra: { client_encoding: 'UTF8' },
    });
    await extDataSource.initialize();
  }, 30_000);

  afterAll(async () => {
    if (insertedModelNames.length) {
      await appDataSource.query(
        `DELETE FROM tracking_links_subscriber WHERE tracking_link_id = ANY($1)`,
        [insertedModelNames],
      );
      await appDataSource.query(
        `DELETE FROM tracking_links_input WHERE id = ANY($1)`,
        [insertedModelNames],
      );
    }
    await extDataSource.destroy();
    await app.close();
  }, 30_000);

  it('classifies subscribers with ≥ 90% overall accuracy', async () => {
    const repo = extDataSource.getRepository(Subscription);

    // 1. Fetch distinct model names
    const models = await repo
      .createQueryBuilder('s')
      .select('DISTINCT s.trackingModelName', 'trackingModelName')
      .where('s.trackingModelName IS NOT NULL')
      .orderBy('s.trackingModelName')
      .limit(MODEL_COUNT)
      .getRawMany<{ trackingModelName: string }>();

    expect(models.length).toBeGreaterThan(0);

    const originalRisk = new Map<string, string>();

    // 2. Send each model's subscribers to the classification endpoint
    for (const { trackingModelName: modelName } of models) {
      const rows = await repo.find({
        where: { trackingModelName: modelName },
      });

      const valid = rows.filter(
        (r) => r.userId && r.subscribedAt && r.riskLevel,
      );
      if (valid.length === 0) continue;

      insertedModelNames.push(modelName);

      for (const r of valid) {
        originalRisk.set(
          `${modelName}::${r.userId}`,
          r.riskLevel.toLowerCase().trim(),
        );
      }

      const subscriptions = valid.map((r) => {
        return {
          id: String(r.id),
          username: r.userName,
          userId: Number(r.userId),
          subscriptionDate:
            r.subscribedAt === 'Not Found'
              ? new Date().toISOString()
              : new Date(r.subscribedAt).toISOString(),
        };
      });

      await request(BASE_URL)
        .post('/tracking-links/input')
        .set('Authorization', `Bearer ${AUTH_KEY}`)
        .send({ trackingLinkId: modelName, subscriptions })
        .expect(201);
    }

    // 3. Trigger the classification job
    await job.processUnprocessed();

    // Diagnostic: check what riskLevels are actually stored in the app DB
    const dbSample: Array<{ risk_level: string; count: string }> =
      await appDataSource.query(
        `SELECT "risk_level", COUNT(*) FROM tracking_links_subscriber GROUP BY "risk_level"`,
      );
    console.log('\nApp DB riskLevel distribution:', dbSample);

    // 4. Fetch results and compare against original labels
    const byRisk = new Map<string, { correct: number; total: number }>();
    let totalCorrect = 0;
    let grandTotal = 0;
    let firstMismatch = true;

    for (const { trackingModelName: modelName } of models) {
      if (!insertedModelNames.includes(modelName)) continue;

      const res = await request(BASE_URL)
        .get(`/tracking-links/${encodeURIComponent(modelName)}`)
        .set('Authorization', `Bearer ${AUTH_KEY}`)
        .query({ page: 1, limit: 1000 })
        .expect(200);

      const subs: Array<{ userId: number; riskLevel: string }> =
        res.body.data ?? [];

      for (const sub of subs) {
        const key = `${modelName}::${sub.userId}`;
        const original = originalRisk.get(key);
        if (original === undefined) continue;

        const computed = (sub.riskLevel ?? '').toLowerCase().trim();

        if (computed !== original && firstMismatch) {
          console.log(
            `\nFirst mismatch — original: "${original}"  computed: "${computed}"  userId: ${sub.userId}  model: ${modelName}`,
          );
          firstMismatch = false;
        }

        if (!byRisk.has(original))
          byRisk.set(original, { correct: 0, total: 0 });
        const bucket = byRisk.get(original)!;
        bucket.total++;
        grandTotal++;

        if (computed === original) {
          bucket.correct++;
          totalCorrect++;
        }
      }
    }

    // 5. Report
    const overallPct = grandTotal ? (totalCorrect / grandTotal) * 100 : 0;
    console.log(
      `\nOverall accuracy: ${overallPct.toFixed(2)}%  (${totalCorrect} / ${grandTotal})\n`,
    );
    const riskOrder = ['no risk', 'low', 'high', 'very high', 'extreme'];
    const levels = [
      ...riskOrder.filter((l) => byRisk.has(l)),
      ...[...byRisk.keys()].filter((l) => !riskOrder.includes(l)),
    ];
    for (const level of levels) {
      const { correct, total } = byRisk.get(level)!;
      const pct = ((correct / total) * 100).toFixed(2);
      console.log(`  ${level.padEnd(14)}: ${pct}%  (${correct} / ${total})`);
    }

    expect(overallPct).toBeGreaterThanOrEqual(90);
  }, 120_000);
});
