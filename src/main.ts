import * as fs from 'fs';
import * as path from 'path';
import { NestFactory } from '@nestjs/core';
import { ValidationPipe } from '@nestjs/common';
import { AppModule } from './app.module';
import { DataSource } from 'typeorm';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import {
  RiskLevel,
  TrackingLinkSubscriber,
} from './tracking-link/entities/tracking-link-subscriber.entity';

const SEED_BATCH = 500;

async function seedIfEmpty(dataSource: DataSource): Promise<void> {
  const repo = dataSource.getRepository(TrackingLinkSubscriber);
  const existing = await repo.count();
  if (existing > 0) {
    console.log(`Seed skip: tracking_links_subscriber has ${existing} rows.`);
    return;
  }

  const seedPath = path.resolve(__dirname, 'seed', 'subscribers.json');
  if (!fs.existsSync(seedPath)) {
    console.log(`Seed skip: ${seedPath} not found.`);
    return;
  }

  const raw = JSON.parse(fs.readFileSync(seedPath, 'utf-8')) as Array<{
    id: string;
    trackingLinkId: string;
    username: string;
    userId: number;
    subscriptionDate: string;
    riskLevel: RiskLevel;
    totalChargebacks: number;
  }>;

  console.log(`Seeding ${raw.length} rows from ${seedPath}...`);
  for (let i = 0; i < raw.length; i += SEED_BATCH) {
    const chunk = raw.slice(i, i + SEED_BATCH).map((r) => ({
      ...r,
      isProcessed: true,
      isInternalData: true,
      isInternalData2: true,
    }));
    await repo.insert(chunk);
    console.log(
      `  inserted ${Math.min(i + SEED_BATCH, raw.length)}/${raw.length}`,
    );
  }
  console.log(`Seed done: ${raw.length} rows inserted.`);
}

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  const config = new DocumentBuilder()
    .setTitle('OF Anti Bot')
    .setDescription('The OF Anti Bot API description')
    .setVersion('1.0')
    .addBearerAuth()
    .build();
  const documentFactory = () => SwaggerModule.createDocument(app, config);
  SwaggerModule.setup('api', app, documentFactory);

  const dataSource = app.get(DataSource);
  await dataSource.runMigrations();
  await seedIfEmpty(dataSource);

  app.useGlobalPipes(new ValidationPipe({ transform: true, whitelist: true }));
  const port = process.env.PORT ?? 3000;
  await app.listen(port, '0.0.0.0');
  console.log(`Listening on 0.0.0.0:${port}`);
}
bootstrap();
