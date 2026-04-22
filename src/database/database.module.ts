import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { TypeOrmModule } from '@nestjs/typeorm';
import { TrackingLinkInput } from '../tracking-link/entities/tracking-link-input.entity';
import { TrackingLinkSubscriber } from '../tracking-link/entities/tracking-link-subscriber.entity';

@Module({
  imports: [
    TypeOrmModule.forRootAsync({
      imports: [ConfigModule],
      useFactory: (config: ConfigService) => ({
        type: 'postgres',
        url: config.get<string>('DB_URL'),
        entities: [TrackingLinkInput, TrackingLinkSubscriber],
        migrations: [__dirname + '/migrations/*.js'],
        synchronize: false,
      }),
      inject: [ConfigService],
    }),
  ],
})
export class DatabaseModule {}
