import { Injectable, Logger } from '@nestjs/common';
import { Cron, CronExpression } from '@nestjs/schedule';
import { TrackingLinkRepository } from './repositories/tracking-link.repository';

@Injectable()
export class TrackingLinkJob {
  private readonly logger = new Logger(TrackingLinkJob.name);

  constructor(private readonly repository: TrackingLinkRepository) {}

  @Cron(CronExpression.EVERY_MINUTE)
  async processUnprocessed(): Promise<void> {
    const links = await this.repository.findUnprocessed();

    if (links.length === 0) return;

    this.logger.log(`Processing ${links.length} unprocessed tracking link(s)`);

    for (const link of links) {
      try {
        await this.repository.refreshCategory(link.id);
      } catch (err) {
        this.logger.error(`Failed to process tracking link "${link.id}"`, err);
      }
    }
  }
}
