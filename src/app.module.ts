import { Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { ConfigModule } from '@nestjs/config';
import { ScheduleModule } from '@nestjs/schedule';
import { DatabaseModule } from './database/database.module';
import { TrackingLinkModule } from './tracking-link/tracking-link.module';
import { BearerAuthGuard } from './auth/bearer-auth.guard';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    ScheduleModule.forRoot(),
    DatabaseModule,
    TrackingLinkModule,
  ],
  providers: [{ provide: APP_GUARD, useClass: BearerAuthGuard }],
})
export class AppModule {}
