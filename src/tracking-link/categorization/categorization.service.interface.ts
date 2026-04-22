import { RiskLevel } from '../entities/tracking-link-subscriber.entity';
import { SubscriberDto } from '../dto/subscriber.dto';

export interface ICategorizationService {
  scoreSubscriber(
    subscriber: SubscriberDto,
    trackingLinkId: string,
  ): Promise<RiskLevel>;

  aggregateRisk(scores: RiskLevel[]): RiskLevel;
}

export const CATEGORIZATION_SERVICE = Symbol('ICategorizationService');
