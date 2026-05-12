import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { EntityManager, Repository } from 'typeorm';
import { UpsertTrackingLinkDto } from '../dto/upsert-tracking-link.dto';
import { TrackingLinkInput } from '../entities/tracking-link-input.entity';
import { TrackingLinkSubscriber } from '../entities/tracking-link-subscriber.entity';
import { TrackingLinkSubscriptionDto } from '../dto/tracking-link-subscription.dto';
import { TrackingLinkDto } from '../dto/tracking-link.dto';
import { SubscriberDto } from '../dto/subscriber.dto';

@Injectable()
export class TrackingLinkRepository {
  constructor(
    @InjectRepository(TrackingLinkInput)
    private readonly inputRepo: Repository<TrackingLinkInput>,
    @InjectRepository(TrackingLinkSubscriber)
    private readonly subscriberRepo: Repository<TrackingLinkSubscriber>,
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

  async upsertSubscribers(
    manager: EntityManager,
    trackingLinkId: string,
    newSubscribers: SubscriberDto[],
  ): Promise<void> {
    const entities = newSubscribers.map((s) =>
      manager.create(TrackingLinkSubscriber, {
        id: `${trackingLinkId}_${s.id}`,
        trackingLinkId,
        username: s.username,
        userId: s.userId,
        subscriptionDate: s.subscriptionDate,
        avatarUrl: s.avatarUrl,
        header: s.header,
        isOnlineMatchesSubscription: s.isOnlineMatchesSubscription,
        isReadingMessages: s.isReadingMessages,
      }),
    );
    await manager.save(TrackingLinkSubscriber, entities);
  }

  async markProcessed(manager: EntityManager, id: string): Promise<void> {
    await manager.update(TrackingLinkInput, id, { isProcessed: true });
  }

  async findAllSubscriptions(
    page: number,
    limit: number,
  ): Promise<[TrackingLinkSubscriptionDto[], number]> {
    const [rows, total] = await this.subscriberRepo.findAndCount({
      where: { isInternalData2: false },
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
      where: {
        trackingLinkId: decodeURIComponent(trackingLinkId),
        isInternalData2: false,
      },
      skip: (page - 1) * limit,
      take: limit,
    });
    return [rows.map(toSubscriptionDto), total];
  }

  async findLinkSummary(trackingLinkId: string): Promise<TrackingLinkDto> {
    const [rows, count] = await this.subscriberRepo.findAndCount({
      where: { trackingLinkId, isInternalData2: false },
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
