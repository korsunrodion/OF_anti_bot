import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { TrackingLinkInput } from './entities/tracking-link-input.entity';
import { TrackingLinkInputController } from './tracking-link-input.controller';
import { TrackingLinkResultsController } from './tracking-link-results.controller';
import { TrackingLinkJob } from './tracking-link.job';
import { TrackingLinkSubscriber } from './entities/tracking-link-subscriber.entity';
import { TrackingLinkRepository } from './repositories/tracking-link.repository';

@Module({
  imports: [
    TypeOrmModule.forFeature([TrackingLinkInput, TrackingLinkSubscriber]),
  ],
  controllers: [TrackingLinkInputController, TrackingLinkResultsController],
  providers: [TrackingLinkRepository, TrackingLinkJob],
})
export class TrackingLinkModule {}
