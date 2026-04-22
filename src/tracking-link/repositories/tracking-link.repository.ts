import { Injectable, Logger, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { DataSource, Repository } from 'typeorm';
import { UpsertTrackingLinkDto } from '../dto/upsert-tracking-link.dto';
import { TrackingLinkInput } from '../entities/tracking-link-input.entity';
import { TrackingLinkSubscriber } from '../entities/tracking-link-subscriber.entity';
import { CategorizationService } from '../categorization/categorization.service';
import { TrackingLinkSubscriptionDto } from '../dto/tracking-link-subscription.dto';
import { TrackingLinkDto } from '../dto/tracking-link.dto';

@Injectable()
export class TrackingLinkRepository {
  private readonly logger = new Logger(TrackingLinkRepository.name);

  constructor(
    @InjectRepository(TrackingLinkInput)
    private readonly inputRepo: Repository<TrackingLinkInput>,
    @InjectRepository(TrackingLinkSubscriber)
    private readonly subscriberRepo: Repository<TrackingLinkSubscriber>,
    private readonly categorizationService: CategorizationService,
    private readonly dataSource: DataSource,
  ) {}

  async upsert(dto: UpsertTrackingLinkDto): Promise<void> {
    await this.inputRepo.save({
      id: dto.trackingLinkId,
      trackingLinkId: dto.trackingLinkId,
      isProcessed: false,
      subscribers: dto.subscriptions,
    });
  }

  async findUnprocessed(): Promise<TrackingLinkInput[]> {
    return this.inputRepo.findBy({ isProcessed: false });
  }

  async refreshCategory(id: string): Promise<void> {
    const input = await this.inputRepo.findOneByOrFail({ id });

    const scores = await Promise.all(
      input.subscribers.map((s) =>
        this.categorizationService.scoreSubscriber(s, id),
      ),
    );
    const riskLevel = this.categorizationService.aggregateRisk(scores);

    const entities = input.subscribers.map((s) =>
      this.subscriberRepo.create({
        id: `${id}_${s.id}`,
        trackingLinkId: id,
        username: s.username,
        userId: s.userId,
        subscriptionDate: s.subscriptionDate,
        riskLevel,
      }),
    );

    await this.dataSource.transaction(async (manager) => {
      await manager.save(TrackingLinkSubscriber, entities);
      await manager.update(TrackingLinkInput, id, { isProcessed: true });
    });

    this.logger.log(
      `Processed tracking link "${id}" with ${entities.length} subscriber(s)`,
    );
  }

  async findAllSubscriptions(
    page: number,
    limit: number,
  ): Promise<[TrackingLinkSubscriptionDto[], number]> {
    const [rows, total] = await this.subscriberRepo.findAndCount({
      skip: (page - 1) * limit,
      take: limit,
    });
    return [rows.map(toSubscriptionDto), total];
  }

  async findSubscriptionsByLinkId(
    trackingLinkId: string,
    page: number,
    limit: number,
  ): Promise<[TrackingLinkSubscriptionDto[], number]> {
    const [rows, total] = await this.subscriberRepo.findAndCount({
      where: { trackingLinkId },
      skip: (page - 1) * limit,
      take: limit,
    });
    return [rows.map(toSubscriptionDto), total];
  }

  async findLinkSummary(trackingLinkId: string): Promise<TrackingLinkDto> {
    const [rows, count] = await this.subscriberRepo.findAndCount({
      where: { trackingLinkId },
    });
    if (count === 0) {
      throw new NotFoundException(
        `No results found for tracking link "${trackingLinkId}"`,
      );
    }
    return { trackingLinkId, riskLevel: rows[0].riskLevel, count };
  }
}

function toSubscriptionDto(
  s: TrackingLinkSubscriber,
): TrackingLinkSubscriptionDto {
  return {
    trackingLinkId: s.trackingLinkId,
    username: s.username,
    userId: s.userId,
    subscriptionDate: s.subscriptionDate,
    riskLevel: s.riskLevel,
  };
}
