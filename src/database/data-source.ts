import { DataSource } from 'typeorm';
import { config } from 'dotenv';
import { TrackingLinkInput } from '../tracking-link/entities/tracking-link-input.entity';
import { TrackingLinkSubscriber } from '../tracking-link/entities/tracking-link-subscriber.entity';

config();

export const AppDataSource = new DataSource({
  type: 'postgres',
  url: process.env.DB_URL,
  entities: [TrackingLinkInput, TrackingLinkSubscriber],
  migrations: ['src/database/migrations/*.ts'],
});
